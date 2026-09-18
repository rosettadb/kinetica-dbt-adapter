import json
from types import SimpleNamespace

import pytest
from dbt.adapters.contracts.connection import AdapterResponse
from dbt.adapters.contracts.relation import RelationType
from dbt_common.exceptions import DbtDatabaseError, DbtRuntimeError
from gpudb import GPUdbException

from dbt.adapters.kinetica.column import KineticaColumn
from dbt.adapters.kinetica.connections import KineticaConnectionManager, KineticaCredentials
from dbt.adapters.kinetica.impl import (
    KineticaAdapter,
    classify_table_description,
    columns_from_type_schema,
)
from dbt.adapters.kinetica.relation import KineticaRelation


class TestCredentials:
    def test_defaults_and_type(self):
        creds = KineticaCredentials(host="http://k:9191")
        assert creds.type == "kinetica"
        assert creds.database == "kinetica"
        assert creds.schema == "ki_home"
        assert creds.unique_field == "http://k:9191"
        assert creds.disable_auto_discovery is True

    def test_aliases(self):
        creds = KineticaCredentials.from_dict(
            {"url": "http://k:9191", "username": "u", "pass": "p", "dbname": "x", "schema": "s"}
        )
        assert creds.host == "http://k:9191"
        assert creds.user == "u"
        assert creds.password == "p"
        assert creds.database == "x"

    def test_connection_info_hides_password(self):
        creds = KineticaCredentials(host="h", user="u", password="secret", schema="s")
        keys = dict(creds.connection_info()).keys()
        assert "password" not in keys
        assert "host" in keys and "schema" in keys


class TestColumn:
    def test_string_sizes(self):
        bounded = KineticaColumn(column="c", dtype="varchar", char_size=16)
        unbounded = KineticaColumn(column="c", dtype="varchar")
        assert bounded.data_type == "varchar(16)"
        assert unbounded.data_type == "varchar"
        assert bounded.can_expand_to(unbounded)
        assert not unbounded.can_expand_to(bounded)
        assert KineticaColumn.string_type(unbounded.string_size()) == "varchar"
        assert KineticaColumn.string_type(32) == "varchar(32)"

    def test_numeric_and_other_types(self):
        dec = KineticaColumn(column="d", dtype="decimal", numeric_precision=10, numeric_scale=2)
        assert dec.is_numeric() and dec.data_type == "decimal(10,2)"
        assert KineticaColumn(column="i", dtype="bigint").is_integer()
        assert KineticaColumn(column="i", dtype="unsigned bigint").is_integer()
        assert KineticaColumn(column="f", dtype="real").is_float()
        assert KineticaColumn(column="v", dtype="vector(3)").data_type == "vector(3)"
        assert KineticaColumn(column="q", dtype="int").quoted == '"q"'

    def test_string_size_on_non_string_raises(self):
        with pytest.raises(DbtRuntimeError):
            KineticaColumn(column="i", dtype="integer").string_size()


class TestRelation:
    def test_render_never_includes_database(self):
        rel = KineticaRelation.create(database="kinetica", schema="s", identifier="t", type="table")
        assert rel.render() == '"s"."t"'
        assert rel.qualified_name() == "s.t"

    def test_rename_and_replace_flags(self):
        table = KineticaRelation.create(schema="s", identifier="t", type=RelationType.Table)
        view = KineticaRelation.create(schema="s", identifier="v", type=RelationType.View)
        assert table.can_be_renamed and table.can_be_replaced
        assert not view.can_be_renamed and view.can_be_replaced

    def test_without_identifier(self):
        rel = KineticaRelation.create(schema="s", identifier="t")
        assert rel.without_identifier().render() == '"s"'


class TestClassify:
    @pytest.mark.parametrize(
        "descs,expected",
        [
            ([], RelationType.Table),
            (["REPLICATED"], RelationType.Table),
            (["RESULT_TABLE"], RelationType.Table),
            (["LOGICAL_VIEW", "VIEW"], RelationType.View),
            (["JOIN", "VIEW"], RelationType.View),
            (["MATERIALIZED_VIEW", "VIEW"], RelationType.MaterializedView),
            (["COLLECTION"], None),
            (["SCHEMA"], None),
            (["MATERIALIZED_VIEW_MEMBER"], None),
        ],
    )
    def test_classify(self, descs, expected):
        assert classify_table_description(descs) == expected


class TestColumnsFromTypeSchema:
    def test_parse(self):
        schema = json.dumps(
            {
                "type": "record",
                "name": "type_name",
                "fields": [
                    {"name": "id", "type": "long"},
                    {"name": "name", "type": ["string", "null"]},
                    {"name": "amount", "type": ["string", "null"]},
                    {"name": "created", "type": "long"},
                ],
            }
        )
        props = {
            "id": ["primary_key", "data"],
            "name": ["char32", "nullable"],
            "amount": ["decimal(12,3)", "nullable"],
            "created": ["timestamp"],
        }
        cols = columns_from_type_schema(schema, props)
        assert [(c.name, c.data_type) for c in cols] == [
            ("id", "bigint"),
            ("name", "varchar(32)"),
            ("amount", "decimal(12,3)"),
            ("created", "timestamp"),
        ]


class TestConnectionManagerStatics:
    def test_get_response_select(self):
        cursor = SimpleNamespace(description=[("a",)], rowcount=3, statement_kind="SELECT")
        resp = KineticaConnectionManager.get_response(cursor)
        assert isinstance(resp, AdapterResponse)
        assert resp.code == "SELECT" and resp.rows_affected == 3
        assert str(resp) == "SELECT 3"

    def test_get_response_ddl(self):
        cursor = SimpleNamespace(description=None, rowcount=-1, statement_kind="CREATE")
        resp = KineticaConnectionManager.get_response(cursor)
        assert resp.code == "CREATE" and resp.rows_affected is None
        assert str(resp) == "CREATE"

    def test_data_type_code_to_name(self):
        assert KineticaConnectionManager.data_type_code_to_name("char16") == "varchar"
        assert KineticaConnectionManager.data_type_code_to_name("long") == "bigint"
        assert KineticaConnectionManager.data_type_code_to_name("timestamp") == "timestamp"

    def test_exception_handler_wraps_gpudb_errors(self):
        manager = KineticaConnectionManager.__new__(KineticaConnectionManager)
        with pytest.raises(DbtDatabaseError) as exc:
            with manager.exception_handler("select boom"):
                raise GPUdbException("[ERROR]: boom")
        assert "boom" in str(exc.value)

    def test_exception_handler_wraps_unknown_errors(self):
        manager = KineticaConnectionManager.__new__(KineticaConnectionManager)
        with pytest.raises(DbtRuntimeError):
            with manager.exception_handler("x"):
                raise ValueError("bad")


class TestAdapterClassmethods:
    def test_static_bits(self):
        assert KineticaAdapter.type() == "kinetica"
        assert KineticaAdapter.date_function() == "now()"
        assert KineticaAdapter.is_cancelable() is False
        assert KineticaAdapter.quote("x") == '"x"'

    def test_convert_types(self):
        import agate

        table = agate.Table.from_object(
            [
                {"i": 1, "f": 1.5, "s": "a", "b": True, "d": "2024-01-01", "dt": "2024-01-01 10:00:00"},
                {"i": 2, "f": 2.5, "s": "b", "b": False, "d": "2024-01-02", "dt": "2024-01-02 10:00:00"},
            ]
        )
        names = table.column_names
        convert = KineticaAdapter.convert_type
        assert convert(table, names.index("i")) == "bigint"
        assert convert(table, names.index("f")) == "double"
        assert convert(table, names.index("s")) == "varchar"
        assert convert(table, names.index("b")) == "boolean"
        assert convert(table, names.index("d")) == "date"
        assert convert(table, names.index("dt")) == "datetime"

    def test_sql_helpers(self):
        adapter = KineticaAdapter.__new__(KineticaAdapter)
        assert adapter.timestamp_add_sql("ts", 2, "day") == "timestampadd(DAY, 2, ts)"
        assert adapter.string_add_sql("c", "x") == "concat(c, 'x')"
        assert adapter.string_add_sql("c", "x", "prepend") == "concat('x', c)"
        assert adapter.valid_incremental_strategies() == ["append", "delete+insert", "microbatch"]
        assert adapter.render_literal("a'b") == "'a''b'"
