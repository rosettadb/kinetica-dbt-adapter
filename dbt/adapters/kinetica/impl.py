import json
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple, TYPE_CHECKING

from dbt.adapters.base import AdapterConfig, ConstraintSupport, available
from dbt.adapters.base.impl import _catalog_filter_schemas
from dbt.adapters.base.relation import BaseRelation, InformationSchema
from dbt.adapters.capability import Capability, CapabilityDict, CapabilitySupport, Support
from dbt.adapters.contracts.relation import RelationType
from dbt.adapters.events.logging import AdapterLogger
from dbt.adapters.sql import SQLAdapter
from dbt_common.contracts.constraints import ConstraintType
from dbt_common.exceptions import DbtRuntimeError

from dbt.adapters.kinetica.column import KineticaColumn
from dbt.adapters.kinetica.connections import KineticaConnectionManager
from dbt.adapters.kinetica.relation import KineticaRelation
from dbt.adapters.kinetica.sql_utils import (
    map_kinetica_type,
    render_literal,
    split_qualified_name,
)

if TYPE_CHECKING:
    import agate

logger = AdapterLogger("Kinetica")

CATALOG_COLUMNS = (
    "table_database",
    "table_schema",
    "table_name",
    "table_type",
    "table_comment",
    "table_owner",
    "column_name",
    "column_index",
    "column_type",
    "column_comment",
)

# Values of `table_descriptions` returned by /show/table.
_MATERIALIZED_VIEW_MARKERS = {"MATERIALIZED_VIEW"}
_VIEW_MARKERS = {"LOGICAL_VIEW", "VIEW", "JOIN"}
_SKIP_MARKERS = {"COLLECTION", "SCHEMA", "MATERIALIZED_VIEW_MEMBER", "MATERIALIZED_VIEW_UNDER_CONSTRUCTION"}


@dataclass
class KineticaConfig(AdapterConfig):
    replicated: Optional[bool] = None
    ttl: Optional[int] = None
    partition_by: Optional[str] = None
    tier_strategy: Optional[str] = None
    table_properties: Optional[Dict[str, Any]] = None
    indexes: Optional[List[Dict[str, Any]]] = None
    refresh: Optional[str] = None  # materialized views: e.g. "EVERY 5 MINUTES"


def classify_table_description(descriptions: Iterable[str]) -> Optional[str]:
    """Map Kinetica's table description flags to a dbt relation type.
    Returns ``None`` for things dbt should ignore (schemas, MV members)."""
    descs = {str(d).upper() for d in descriptions or ()}
    if descs & _MATERIALIZED_VIEW_MARKERS:
        return RelationType.MaterializedView
    if descs & _SKIP_MARKERS:
        return None
    if descs & _VIEW_MARKERS:
        return RelationType.View
    return RelationType.Table


def columns_from_type_schema(
    type_schema: str, properties: Optional[Dict[str, List[str]]]
) -> List[KineticaColumn]:
    """Build dbt columns from a Kinetica Avro type schema + column properties."""
    schema = json.loads(type_schema) if isinstance(type_schema, str) else (type_schema or {})
    properties = properties or {}
    columns: List[KineticaColumn] = []
    for field in schema.get("fields", []):
        name = field.get("name")
        avro_type = field.get("type")
        if isinstance(avro_type, list):
            non_null = [t for t in avro_type if t != "null"]
            avro_type = non_null[0] if non_null else "string"
        if isinstance(avro_type, dict):
            avro_type = avro_type.get("type", "string")
        dtype, char_size, precision, scale = map_kinetica_type(
            str(avro_type), properties.get(name, [])
        )
        columns.append(
            KineticaColumn(
                column=name,
                dtype=dtype,
                char_size=char_size,
                numeric_precision=precision,
                numeric_scale=scale,
            )
        )
    return columns


class KineticaAdapter(SQLAdapter):
    Relation = KineticaRelation
    Column = KineticaColumn
    ConnectionManager = KineticaConnectionManager
    AdapterSpecificConfigs = KineticaConfig

    CONSTRAINT_SUPPORT = {
        ConstraintType.check: ConstraintSupport.NOT_SUPPORTED,
        ConstraintType.not_null: ConstraintSupport.ENFORCED,
        ConstraintType.unique: ConstraintSupport.NOT_SUPPORTED,
        ConstraintType.primary_key: ConstraintSupport.ENFORCED,
        ConstraintType.foreign_key: ConstraintSupport.NOT_ENFORCED,
    }

    _capabilities = CapabilityDict(
        {
            Capability.SchemaMetadataByRelations: CapabilitySupport(support=Support.Full),
            Capability.TableLastModifiedMetadata: CapabilitySupport(support=Support.Unsupported),
        }
    )

    # ---- basics ------------------------------------------------------------ #
    @classmethod
    def date_function(cls) -> str:
        return "now()"

    @classmethod
    def is_cancelable(cls) -> bool:
        return False

    @classmethod
    def quote(cls, identifier: str) -> str:
        return '"{}"'.format(identifier)

    @classmethod
    def convert_text_type(cls, agate_table: "agate.Table", col_idx: int) -> str:
        return "varchar"

    @classmethod
    def convert_number_type(cls, agate_table: "agate.Table", col_idx: int) -> str:
        import agate

        decimals = agate_table.aggregate(agate.MaxPrecision(col_idx))
        return "double" if decimals else "bigint"

    @classmethod
    def convert_integer_type(cls, agate_table: "agate.Table", col_idx: int) -> str:
        return "bigint"

    @classmethod
    def convert_boolean_type(cls, agate_table: "agate.Table", col_idx: int) -> str:
        return "boolean"

    @classmethod
    def convert_datetime_type(cls, agate_table: "agate.Table", col_idx: int) -> str:
        return "datetime"

    @classmethod
    def convert_date_type(cls, agate_table: "agate.Table", col_idx: int) -> str:
        return "date"

    @classmethod
    def convert_time_type(cls, agate_table: "agate.Table", col_idx: int) -> str:
        return "time"

    def valid_incremental_strategies(self) -> List[str]:
        return ["append", "delete+insert", "microbatch"]

    def timestamp_add_sql(self, add_to: str, number: int = 1, interval: str = "hour") -> str:
        return f"timestampadd({interval.upper()}, {number}, {add_to})"

    def string_add_sql(self, add_to: str, value: str, location: str = "append") -> str:
        if location == "append":
            return f"concat({add_to}, '{value}')"
        elif location == "prepend":
            return f"concat('{value}', {add_to})"
        raise DbtRuntimeError(f'Got an unexpected location value of "{location}"')

    @available
    def render_literal(self, value: Any) -> str:
        """Render a Python value as a Kinetica literal (used by seeds)."""
        return render_literal(value)

    # ---- native metadata access ------------------------------------------- #
    def _handle(self):
        return self.connections.get_thread_connection().handle

    def list_schemas(self, database: str) -> List[str]:
        with self.connections.exception_handler("show_schema('')"):
            response = self._handle().show_schema("", {"no_error_if_not_exists": "true"})
        return list(response.get("schema_names") or [])

    def check_schema_exists(self, database: str, schema: str) -> bool:
        with self.connections.exception_handler(f"show_schema({schema!r})"):
            response = self._handle().show_schema(schema, {"no_error_if_not_exists": "true"})
        return schema in (response.get("schema_names") or [])

    def _show_children(self, schema: str) -> Any:
        with self.connections.exception_handler(f"show_table({schema!r})"):
            return self._handle().show_table(
                schema,
                {
                    "show_children": "true",
                    "no_error_if_not_exists": "true",
                    "skip_additional_info": "true",
                },
            )

    def _show_relation(self, relation: BaseRelation) -> Any:
        name = f"{relation.schema}.{relation.identifier}" if relation.schema else relation.identifier
        with self.connections.exception_handler(f"show_table({name!r})"):
            return self._handle().show_table(
                name,
                {
                    "show_children": "false",
                    "no_error_if_not_exists": "true",
                    "skip_additional_info": "true",
                },
            )

    def list_relations_without_caching(self, schema_relation: BaseRelation) -> List[BaseRelation]:
        schema = schema_relation.schema
        if not schema:
            return []
        response = self._show_children(schema)
        names = response.get("table_names") or []
        descriptions = response.get("table_descriptions") or []
        quote_policy = {"database": False, "schema": True, "identifier": True}

        relations: List[BaseRelation] = []
        for idx, name in enumerate(names):
            desc = descriptions[idx] if idx < len(descriptions) else []
            rel_type = classify_table_description(desc)
            if rel_type is None:
                continue
            rel_schema, identifier = split_qualified_name(name, schema)
            relations.append(
                self.Relation.create(
                    database=schema_relation.database,
                    schema=rel_schema,
                    identifier=identifier,
                    type=rel_type,
                    quote_policy=quote_policy,
                )
            )
        return relations

    @available.parse_list
    def get_columns_in_relation(self, relation: BaseRelation) -> List[KineticaColumn]:
        response = self._show_relation(relation)
        names = response.get("table_names") or []
        if not names:
            return []
        type_schemas = response.get("type_schemas") or []
        properties = response.get("properties") or []
        if not type_schemas:
            return []
        return columns_from_type_schema(type_schemas[0], properties[0] if properties else {})

    # ---- catalog (dbt docs generate) --------------------------------------- #
    def _catalog_rows_for_table(
        self, schema: str, name: str, description: Iterable[str], type_schema: str, props: Dict
    ) -> List[Tuple[Any, ...]]:
        rel_type = classify_table_description(description)
        if rel_type is None:
            return []
        rel_schema, identifier = split_qualified_name(name, schema)
        table_type = "BASE TABLE" if rel_type == RelationType.Table else str(rel_type).upper()
        database = self.config.credentials.database
        rows: List[Tuple[Any, ...]] = []
        for index, column in enumerate(columns_from_type_schema(type_schema, props), start=1):
            rows.append(
                (
                    database,
                    rel_schema,
                    identifier,
                    table_type,
                    None,
                    None,
                    column.name,
                    index,
                    column.data_type,
                    None,
                )
            )
        return rows

    def _catalog_rows_for_schema(self, schema: str) -> List[Tuple[Any, ...]]:
        response = self._show_children(schema)
        names = response.get("table_names") or []
        descriptions = response.get("table_descriptions") or []
        type_schemas = response.get("type_schemas") or []
        properties = response.get("properties") or []
        rows: List[Tuple[Any, ...]] = []
        for idx, name in enumerate(names):
            desc = descriptions[idx] if idx < len(descriptions) else []
            type_schema = type_schemas[idx] if idx < len(type_schemas) else "{}"
            props = properties[idx] if idx < len(properties) else {}
            rows.extend(self._catalog_rows_for_table(schema, name, desc, type_schema, props))
        return rows

    def _catalog_rows_for_relation(self, relation: BaseRelation) -> List[Tuple[Any, ...]]:
        response = self._show_relation(relation)
        names = response.get("table_names") or []
        if not names:
            return []
        descriptions = response.get("table_descriptions") or [[]]
        type_schemas = response.get("type_schemas") or ["{}"]
        properties = response.get("properties") or [{}]
        return self._catalog_rows_for_table(
            relation.schema or "", names[0], descriptions[0], type_schemas[0], properties[0]
        )

    def _rows_to_catalog_table(self, rows: List[Tuple[Any, ...]]) -> "agate.Table":
        from dbt_common.clients.agate_helper import table_from_rows

        return table_from_rows(
            rows,
            CATALOG_COLUMNS,
            text_only_columns=[
                "table_database",
                "table_schema",
                "table_name",
                "table_type",
                "table_comment",
                "table_owner",
                "column_name",
                "column_type",
                "column_comment",
            ],
        )

    def _get_one_catalog(
        self,
        information_schema: InformationSchema,
        schemas: Set[str],
        used_schemas: FrozenSet[Tuple[str, str]],
    ) -> "agate.Table":
        rows: List[Tuple[Any, ...]] = []
        for schema in schemas:
            if schema:
                rows.extend(self._catalog_rows_for_schema(schema))
        table = self._rows_to_catalog_table(rows)
        return self._catalog_filter_table(table, used_schemas)

    def _get_one_catalog_by_relations(
        self,
        information_schema: InformationSchema,
        relations: List[BaseRelation],
        used_schemas: FrozenSet[Tuple[str, str]],
    ) -> "agate.Table":
        rows: List[Tuple[Any, ...]] = []
        for relation in relations:
            rows.extend(self._catalog_rows_for_relation(relation))
        table = self._rows_to_catalog_table(rows)
        return self._catalog_filter_table(table, used_schemas)

    # ---- misc --------------------------------------------------------------- #
    def get_rows_different_sql(
        self,
        relation_a: BaseRelation,
        relation_b: BaseRelation,
        column_names: Optional[List[str]] = None,
        except_operator: str = "EXCEPT",
    ) -> str:
        names: List[str]
        if column_names is None:
            columns = self.get_columns_in_relation(relation_a)
            names = sorted((self.quote(c.name) for c in columns))
        else:
            names = sorted((self.quote(n) for n in column_names))
        columns_csv = ", ".join(names)
        return KINETICA_COLUMNS_EQUAL_SQL.format(
            columns=columns_csv,
            relation_a=str(relation_a),
            relation_b=str(relation_b),
            except_op=except_operator,
        )

    def debug_query(self) -> None:
        self.execute("select 1 as id")


KINETICA_COLUMNS_EQUAL_SQL = """
with diff_count as (
    select
        1 as id,
        count(*) as num_missing from (
            (select {columns} from {relation_a} {except_op}
             select {columns} from {relation_b})
             union all
            (select {columns} from {relation_b} {except_op}
             select {columns} from {relation_a})
        ) as a
), table_a as (
    select count(*) as num_rows from {relation_a}
), table_b as (
    select count(*) as num_rows from {relation_b}
), row_count_diff as (
    select
        1 as id,
        table_a.num_rows - table_b.num_rows as difference
    from table_a, table_b
)
select
    row_count_diff.difference as row_count_difference,
    diff_count.num_missing as num_mismatched
from row_count_diff
join diff_count on row_count_diff.id = diff_count.id
""".strip()
