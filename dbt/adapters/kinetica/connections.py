import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, Optional, Tuple, Type

from dbt.adapters.contracts.connection import (
    AdapterResponse,
    Connection,
    ConnectionState,
    Credentials,
)
from dbt.adapters.events.logging import AdapterLogger
from dbt.adapters.events.types import ConnectionUsed, SQLQuery, SQLQueryStatus, AdapterEventDebug
from dbt.adapters.sql import SQLConnectionManager
from dbt_common.events.contextvars import get_node_info
from dbt_common.events.functions import fire_event
from dbt_common.exceptions import DbtDatabaseError, DbtRuntimeError
from dbt_common.utils import cast_to_str
from gpudb import GPUdbConnectionException, GPUdbException

from dbt.adapters.kinetica.client import DEFAULT_PAGE_SIZE, KineticaHandle
from dbt.adapters.kinetica.sql_utils import map_kinetica_type

logger = AdapterLogger("Kinetica")


class KineticaRetryableConnectionError(Exception):
    """Raised while opening a connection when the failure looks transient."""


@dataclass
class KineticaCredentials(Credentials):
    host: str = "http://localhost:9191"
    user: Optional[str] = None
    password: Optional[str] = None
    # Kinetica has no database/catalog concept. dbt requires one, so this is a
    # label only; it is never rendered into SQL.
    database: str = "kinetica"
    schema: str = "ki_home"
    timeout: Optional[int] = None  # seconds; None = wait indefinitely
    skip_ssl_cert_verification: bool = False
    disable_auto_discovery: bool = True
    disable_failover: bool = False
    oauth_token: Optional[str] = None
    retries: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    http_headers: Optional[Dict[str, str]] = None
    # Extra options forwarded to every /execute/sql call, e.g. {"ttl": "60"}
    sql_options: Optional[Dict[str, Any]] = None

    _ALIASES: ClassVar[Dict[str, str]] = field(
        default={
            "url": "host",
            "username": "user",
            "pass": "password",
            "passwd": "password",
            "dbname": "database",
        },
        init=False,
    )

    @property
    def type(self) -> str:
        return "kinetica"

    @property
    def unique_field(self) -> str:
        return self.host

    def _connection_keys(self) -> Tuple[str, ...]:
        return (
            "host",
            "user",
            "database",
            "schema",
            "timeout",
            "skip_ssl_cert_verification",
            "disable_auto_discovery",
            "disable_failover",
            "retries",
            "page_size",
        )


class KineticaConnectionManager(SQLConnectionManager):
    TYPE = "kinetica"

    # ---- error handling ---------------------------------------------------- #
    @contextmanager
    def exception_handler(self, sql: str):
        try:
            yield
        except GPUdbException as exc:
            message = getattr(exc, "message", None) or str(exc)
            logger.debug(f"Kinetica error while running:\n{sql}")
            logger.debug(message)
            raise DbtDatabaseError(message) from exc
        except DbtRuntimeError:
            raise
        except Exception as exc:
            logger.debug(f"Error while running:\n{sql}")
            logger.debug(str(exc))
            raise DbtRuntimeError(str(exc)) from exc

    # ---- lifecycle --------------------------------------------------------- #
    @classmethod
    def open(cls, connection: Connection) -> Connection:
        if connection.state == ConnectionState.OPEN:
            logger.debug("Connection is already open, skipping open.")
            return connection

        credentials: KineticaCredentials = connection.credentials

        def connect() -> KineticaHandle:
            try:
                return KineticaHandle.from_credentials(credentials)
            except GPUdbConnectionException:
                raise
            except GPUdbException as exc:
                is_transient = False
                try:
                    is_transient = exc.is_connection_failure()
                except Exception:
                    is_transient = False
                if is_transient:
                    raise KineticaRetryableConnectionError(str(exc)) from exc
                raise

        retryable: Tuple[Type[Exception], ...] = (
            GPUdbConnectionException,
            KineticaRetryableConnectionError,
            ConnectionError,
            TimeoutError,
        )

        return cls.retry_connection(
            connection,
            connect=connect,
            logger=logger,
            retry_limit=max(int(credentials.retries or 0), 0),
            retry_timeout=lambda attempt: min(2**attempt, 30),
            retryable_exceptions=retryable,
        )

    def cancel(self, connection: Connection) -> None:
        # Kinetica has no per-statement cancel in the HTTP API; nothing to do.
        logger.debug(f"Cancel requested for connection {connection.name}; not supported.")

    @classmethod
    def is_cancelable(cls) -> bool:
        return False

    # ---- transactions (Kinetica auto-commits) ------------------------------ #
    def begin(self) -> Connection:
        connection = self.get_thread_connection()
        connection.transaction_open = True
        return connection

    def commit(self) -> Connection:
        connection = self.get_thread_connection()
        connection.transaction_open = False
        return connection

    @classmethod
    def _rollback_handle(cls, connection: Connection) -> None:
        return None

    def add_begin_query(self):  # pragma: no cover - begin() never issues SQL
        return None

    def add_commit_query(self):  # pragma: no cover - commit() never issues SQL
        return None

    # ---- execution --------------------------------------------------------- #
    def add_query(
        self,
        sql: str,
        auto_begin: bool = True,
        bindings: Optional[Any] = None,
        abridge_sql_log: bool = False,
        retryable_exceptions: Tuple[Type[Exception], ...] = tuple(),
        retry_limit: int = 1,
        fetch_limit: Optional[int] = None,
    ) -> Tuple[Connection, Any]:
        connection = self.get_thread_connection()
        if auto_begin and connection.transaction_open is False:
            self.begin()

        fire_event(
            ConnectionUsed(
                conn_type=self.TYPE,
                conn_name=cast_to_str(connection.name),
                node_info=get_node_info(),
            )
        )

        with self.exception_handler(sql):
            log_sql = "{}...".format(sql[:512]) if abridge_sql_log else sql
            fire_event(
                SQLQuery(
                    conn_name=cast_to_str(connection.name),
                    sql=log_sql,
                    node_info=get_node_info(),
                )
            )

            pre = time.perf_counter()
            cursor = connection.handle.cursor()

            attempt = 1
            while True:
                try:
                    cursor.execute(sql, bindings, limit=fetch_limit)
                    break
                except retryable_exceptions as exc:
                    if attempt >= retry_limit:
                        raise exc
                    fire_event(
                        AdapterEventDebug(
                            base_msg=f"Got a retryable error {type(exc)}. "
                            f"{retry_limit - attempt} retries left. Retrying in 1 second.\n"
                            f"Error:\n{exc}"
                        )
                    )
                    time.sleep(1)
                    attempt += 1

            response = self.get_response(cursor)
            fire_event(
                SQLQueryStatus(
                    status=str(response),
                    elapsed=time.perf_counter() - pre,
                    node_info=get_node_info(),
                    query_id=response.query_id,
                )
            )
            return connection, cursor

    def execute(
        self,
        sql: str,
        auto_begin: bool = False,
        fetch: bool = False,
        limit: Optional[int] = None,
    ) -> Tuple[AdapterResponse, Any]:
        from dbt_common.clients.agate_helper import empty_table

        sql = self._add_query_comment(sql)
        _, cursor = self.add_query(sql, auto_begin, fetch_limit=limit if fetch else None)
        response = self.get_response(cursor)
        if fetch:
            table = self.get_result_from_cursor(cursor, limit)
        else:
            table = empty_table()
        return response, table

    @classmethod
    def get_response(cls, cursor: Any) -> AdapterResponse:
        rowcount = getattr(cursor, "rowcount", -1)
        if getattr(cursor, "description", None):
            code = "SELECT"
        else:
            code = getattr(cursor, "statement_kind", "") or "OK"
        rows_affected = rowcount if isinstance(rowcount, int) and rowcount >= 0 else None
        message = f"{code} {rows_affected}" if rows_affected is not None else code
        return AdapterResponse(_message=message, code=code, rows_affected=rows_affected)

    @classmethod
    def data_type_code_to_name(cls, type_code: Any) -> str:
        return map_kinetica_type(str(type_code))[0]
