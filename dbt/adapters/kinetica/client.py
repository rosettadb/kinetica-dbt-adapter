"""A thin DB-API-flavoured wrapper around the Kinetica ``gpudb`` client.

dbt's SQL connection manager expects ``handle.cursor()``, ``cursor.execute()``,
``cursor.description``, ``cursor.fetchall()`` and friends.  Kinetica's native
client speaks ``/execute/sql`` over HTTP instead, so this module adapts one to
the other."""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from gpudb import GPUdb, GPUdbException

from dbt.adapters.kinetica.sql_utils import (
    bind_parameters,
    first_keyword,
    is_transaction_control,
    looks_like_query,
    split_sql_statements,
    value_converter,
)

DEFAULT_PAGE_SIZE = 10000
PAGING_TABLE_TTL_MINUTES = 20


@dataclass
class KineticaQueryResult:
    columns: List[Tuple[str, str]] = field(default_factory=list)  # (name, kinetica datatype)
    rows: List[tuple] = field(default_factory=list)
    total_number_of_records: int = 0
    has_more_records: bool = False
    count_affected: int = 0
    paging_table: str = ""
    result_table_list: List[str] = field(default_factory=list)


def _stringify_options(options: Optional[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in (options or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[str(key)] = "true" if value else "false"
        else:
            out[str(key)] = str(value)
    return out


def decode_json_result(payload_str: Optional[str]) -> Tuple[List[Tuple[str, str]], List[tuple]]:
    """Decode Kinetica's JSON-encoded, column-major result payload."""
    if not payload_str:
        return [], []
    try:
        payload = json.loads(payload_str)
    except ValueError:
        return [], []
    if not isinstance(payload, dict):
        return [], []
    headers = payload.get("column_headers")
    if not headers:
        return [], []
    datatypes = payload.get("column_datatypes") or []
    columns = [
        (str(name), str(datatypes[i]) if i < len(datatypes) else "string")
        for i, name in enumerate(headers)
    ]
    col_values = [payload.get(f"column_{i + 1}") or [] for i in range(len(headers))]
    nrows = len(col_values[0]) if col_values else 0
    converters = [value_converter(dtype) for _, dtype in columns]

    rows: List[tuple] = []
    for r in range(nrows):
        row = []
        for conv, values in zip(converters, col_values):
            value = values[r] if r < len(values) else None
            row.append(conv(value) if (conv and value is not None) else value)
        rows.append(tuple(row))
    return columns, rows


class KineticaHandle:
    """Owns one ``GPUdb`` client.  Created per dbt thread."""

    def __init__(
        self,
        db: GPUdb,
        base_options: Optional[Dict[str, Any]] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        self.db = db
        self.base_options = _stringify_options(base_options)
        self.page_size = max(int(page_size or DEFAULT_PAGE_SIZE), 1)
        self._closed = False

    # ---- construction ---------------------------------------------------- #
    @classmethod
    def from_credentials(cls, credentials: Any) -> "KineticaHandle":
        from dbt.adapters.kinetica.__version__ import version

        options = GPUdb.Options()
        options.username = credentials.user or ""
        options.password = credentials.password or ""
        if getattr(credentials, "oauth_token", None):
            options.oauth_token = credentials.oauth_token
        options.skip_ssl_cert_verification = bool(credentials.skip_ssl_cert_verification)
        options.disable_auto_discovery = bool(credentials.disable_auto_discovery)
        options.disable_failover = bool(credentials.disable_failover)
        if credentials.timeout is not None:
            # profile value is seconds; the client wants milliseconds
            options.timeout = int(credentials.timeout) * 1000
        if credentials.http_headers:
            options.http_headers = dict(credentials.http_headers)
        options.client_name = "dbt-kinetica"
        options.client_version = version

        db = GPUdb(host=credentials.host, options=options)
        return cls(
            db,
            base_options=credentials.sql_options or {},
            page_size=credentials.page_size,
        )

    # ---- DB-API-ish surface --------------------------------------------- #
    def cursor(self) -> "KineticaCursor":
        return KineticaCursor(self)

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.db.__exit__(None, None, None)
        except Exception:  # pragma: no cover - best effort cleanup
            pass

    def commit(self) -> None:  # Kinetica auto-commits
        return None

    def rollback(self) -> None:  # nothing to roll back
        return None

    # ---- native calls ---------------------------------------------------- #
    @staticmethod
    def _check(response: Any, context: str) -> Any:
        status_info = response.get("status_info", {}) if hasattr(response, "get") else {}
        status = status_info.get("status", "OK")
        if status != "OK":
            message = status_info.get("message", "unknown error")
            raise GPUdbException(f"{context} failed [{status}]: {message}")
        return response

    def execute_sql(
        self,
        statement: str,
        offset: int = 0,
        limit: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> KineticaQueryResult:
        opts = dict(self.base_options)
        opts.update(_stringify_options(options))
        page = self.page_size if limit is None else max(int(limit), 1)

        response = self.db.execute_sql(
            statement=statement,
            offset=int(offset),
            limit=int(page),
            encoding="json",
            options=opts,
        )
        self._check(response, "execute_sql")

        columns, rows = decode_json_result(response.get("json_encoded_response"))
        info = response.get("info") or {}
        result_tables = info.get("result_table_list") or ""
        return KineticaQueryResult(
            columns=columns,
            rows=rows,
            total_number_of_records=int(response.get("total_number_of_records") or 0),
            has_more_records=bool(response.get("has_more_records")),
            count_affected=int(response.get("count_affected") or 0),
            paging_table=response.get("paging_table") or "",
            result_table_list=[t for t in result_tables.split(",") if t],
        )

    def clear_table(self, table_name: str) -> None:
        try:
            self.db.clear_table(table_name, options={"no_error_if_not_exists": "true"})
        except Exception:  # pragma: no cover - best effort cleanup
            pass

    def show_table(self, table_name: str, options: Optional[Dict[str, Any]] = None) -> Any:
        response = self.db.show_table(table_name, options=_stringify_options(options))
        return self._check(response, f"show_table({table_name!r})")

    def show_schema(self, schema_name: str, options: Optional[Dict[str, Any]] = None) -> Any:
        response = self.db.show_schema(schema_name, options=_stringify_options(options))
        return self._check(response, f"show_schema({schema_name!r})")


class KineticaCursor:
    """Executes one or more ``;``-separated statements, keeping the result of the
    last one.  Multi-page result sets are fetched lazily."""

    arraysize = 1

    def __init__(self, handle: KineticaHandle) -> None:
        self._handle = handle
        self.description: Optional[List[Tuple[Any, ...]]] = None
        self.rowcount: int = -1
        self.statement_kind: str = ""
        self._reset_result()

    # ---- internals --------------------------------------------------------- #
    def _reset_result(self) -> None:
        self._cleanup_paging()
        self._statement: Optional[str] = None
        self._rows: List[tuple] = []
        self._pos = 0
        self._offset = 0
        self._has_more = False
        self._limit: Optional[int] = None
        self._paging_options: Dict[str, str] = {}
        self._paging_tables: List[str] = []
        self.description = None
        self.rowcount = -1

    def _cleanup_paging(self) -> None:
        tables = getattr(self, "_paging_tables", None) or []
        for table in tables:
            self._handle.clear_table(table)
        self._paging_tables = []

    def _run(self, statement: str, limit: Optional[int]) -> None:
        self._limit = limit
        page_size = self._handle.page_size
        first_page = page_size
        if limit is not None and 0 < limit < page_size:
            first_page = limit

        options: Dict[str, str] = {}
        if looks_like_query(statement):
            # Ask the server to persist multi-page results so that paging is
            # stable; the tables are cleared once we're done (and expire anyway).
            options = {
                "paging_table": f"dbt_paging_{uuid.uuid4().hex}",
                "paging_table_ttl": str(PAGING_TABLE_TTL_MINUTES),
            }

        result = self._handle.execute_sql(statement, offset=0, limit=first_page, options=options)
        self._statement = statement
        self.statement_kind = first_keyword(statement).upper()

        # Kinetica answers DDL/DML with a one-row `dummy` result set; only treat
        # the response as a result set when the statement is actually a query.
        if result.columns and looks_like_query(statement):
            self.description = [
                (name, dtype, None, None, None, None, None) for name, dtype in result.columns
            ]
            self._rows = list(result.rows)
            self._offset = len(self._rows)
            self._has_more = result.has_more_records
            self.rowcount = result.total_number_of_records or len(self._rows)
            if result.paging_table:
                self._paging_options = {"paging_table": result.paging_table}
                self._paging_tables = [result.paging_table] + list(result.result_table_list)
            elif self._has_more and options:
                self._paging_options = {"paging_table": options["paging_table"]}
                self._paging_tables = [options["paging_table"]]
        else:
            self.description = None
            self._rows = []
            self._offset = 0
            self._has_more = False
            self.rowcount = result.count_affected

        if not self._has_more:
            self._cleanup_paging()

    def _needed(self) -> Optional[int]:
        return self._limit if (self._limit is not None and self._limit > 0) else None

    def _fetch_pages(self, want: Optional[int]) -> None:
        """Fetch further pages until we hold ``want`` rows (or everything)."""
        while self._has_more and self._statement is not None:
            needed = self._needed()
            if needed is not None and len(self._rows) >= needed:
                break
            if want is not None and len(self._rows) >= want:
                break
            page = self._handle.page_size
            if needed is not None:
                page = min(page, needed - len(self._rows))
            result = self._handle.execute_sql(
                self._statement, offset=self._offset, limit=page, options=self._paging_options
            )
            if not result.rows:
                self._has_more = False
                break
            self._rows.extend(result.rows)
            self._offset += len(result.rows)
            self._has_more = result.has_more_records
        if not self._has_more:
            self._cleanup_paging()
        needed = self._needed()
        if needed is not None and len(self._rows) > needed:
            self._rows = self._rows[:needed]

    # ---- DB-API surface ---------------------------------------------------- #
    def execute(
        self, sql: str, bindings: Optional[Sequence[Any]] = None, limit: Optional[int] = None
    ) -> "KineticaCursor":
        if bindings:
            sql = bind_parameters(sql, bindings)
        self._reset_result()
        statements = split_sql_statements(sql)
        for statement in statements:
            if is_transaction_control(statement):
                continue
            self._run(statement, limit)
        return self

    def fetchall(self) -> List[tuple]:
        self._fetch_pages(None)
        rows = self._rows[self._pos :]
        self._pos = len(self._rows)
        return rows

    def fetchmany(self, size: Optional[int] = None) -> List[tuple]:
        size = size or self.arraysize
        self._fetch_pages(self._pos + size)
        rows = self._rows[self._pos : self._pos + size]
        self._pos += len(rows)
        return rows

    def fetchone(self) -> Optional[tuple]:
        rows = self.fetchmany(1)
        return rows[0] if rows else None

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row

    def close(self) -> None:
        self._cleanup_paging()
        self._rows = []
        self._has_more = False
