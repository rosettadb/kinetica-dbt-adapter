import datetime
import decimal

import pytest

from dbt.adapters.kinetica.sql_utils import (
    UNBOUNDED_STRING_SIZE,
    bind_parameters,
    first_keyword,
    is_transaction_control,
    looks_like_query,
    map_kinetica_type,
    render_literal,
    split_qualified_name,
    split_sql_statements,
    strip_sql_comments,
    value_converter,
)


class TestSplitStatements:
    def test_simple_split(self):
        assert split_sql_statements("select 1; select 2") == ["select 1", "select 2"]

    def test_trailing_semicolon_and_blank_chunks(self):
        assert split_sql_statements("select 1;;  ;") == ["select 1"]

    def test_semicolon_inside_string_literal(self):
        sql = "insert into t values ('a;b', 'it''s; fine'); select 1"
        assert split_sql_statements(sql) == [
            "insert into t values ('a;b', 'it''s; fine')",
            "select 1",
        ]

    def test_semicolon_inside_quoted_identifier(self):
        sql = 'select "we;ird" from t; select 2'
        assert split_sql_statements(sql) == ['select "we;ird" from t', "select 2"]

    def test_semicolon_inside_comments(self):
        sql = "-- a; comment\nselect 1 /* block; comment */; select 2"
        assert split_sql_statements(sql) == [
            "-- a; comment\nselect 1 /* block; comment */",
            "select 2",
        ]

    def test_comment_only_chunk_is_dropped(self):
        assert split_sql_statements("/* header */ ; select 1") == ["select 1"]

    def test_dbt_query_header_stays_attached(self):
        sql = '/* {"app": "dbt"} */\nselect 1'
        assert split_sql_statements(sql) == [sql]


class TestComments:
    def test_strip(self):
        assert strip_sql_comments("select 1 -- x\n/* y */ from t").split() == ["select", "1", "from", "t"]

    def test_first_keyword(self):
        assert first_keyword("/* hdr */ \n  SELECT 1") == "select"
        assert first_keyword("(select 1) union all (select 2)") == "("
        assert first_keyword("  ") == ""

    def test_transaction_control(self):
        assert is_transaction_control("commit;")
        assert is_transaction_control("/* x */ BEGIN")
        assert is_transaction_control("start transaction")
        assert not is_transaction_control("commit_table")
        assert not is_transaction_control("select 1")

    def test_looks_like_query(self):
        assert looks_like_query("with a as (select 1) select * from a")
        assert looks_like_query("explain select 1")
        assert not looks_like_query("create table x as (select 1)")
        assert not looks_like_query("insert into x select 1")


class TestLiterals:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, "NULL"),
            (True, "1"),
            (False, "0"),
            (42, "42"),
            (1.5, "1.5"),
            (float("nan"), "NULL"),
            (decimal.Decimal("10.250"), "10.250"),
            ("it's", "'it''s'"),
            (datetime.date(2024, 1, 2), "'2024-01-02'"),
            (datetime.datetime(2024, 1, 2, 3, 4, 5, 678000), "'2024-01-02 03:04:05.678'"),
            (datetime.time(3, 4, 5), "'03:04:05.000'"),
        ],
    )
    def test_render_literal(self, value, expected):
        assert render_literal(value) == expected

    def test_bind_parameters(self):
        assert bind_parameters("insert into t values (%s, %s)", ["a'b", 3]) == (
            "insert into t values ('a''b', 3)"
        )

    def test_bind_parameters_escaped_percent(self):
        assert bind_parameters("select '100%%' where x = %s", [1]) == "select '100%' where x = 1"

    def test_bind_parameters_count_mismatch(self):
        with pytest.raises(ValueError):
            bind_parameters("select %s, %s", [1])
        with pytest.raises(ValueError):
            bind_parameters("select 1", [1])
        # no bindings at all means "nothing to substitute"
        assert bind_parameters("select '%s'", []) == "select '%s'"


class TestTypeMapping:
    @pytest.mark.parametrize(
        "base,props,expected",
        [
            ("int", [], ("integer", None, None, None)),
            ("int", ["int8"], ("tinyint", None, None, None)),
            ("int", ["int16", "data"], ("smallint", None, None, None)),
            ("int", ["boolean"], ("boolean", None, None, None)),
            ("long", [], ("bigint", None, None, None)),
            ("long", ["timestamp"], ("timestamp", None, None, None)),
            ("long", ["ulong"], ("unsigned bigint", None, None, None)),
            ("float", [], ("real", None, None, None)),
            ("double", ["data"], ("double", None, None, None)),
            ("string", [], ("varchar", None, None, None)),
            ("string", ["char16", "nullable", "primary_key"], ("varchar", 16, None, None)),
            ("string", ["date"], ("date", None, None, None)),
            ("string", ["datetime"], ("datetime", None, None, None)),
            ("string", ["time"], ("time", None, None, None)),
            ("string", ["decimal"], ("decimal", None, 18, 4)),
            ("string", ["decimal(10,2)"], ("decimal", None, 10, 2)),
            ("string", ["uuid"], ("uuid", None, None, None)),
            ("string", ["ipv4"], ("ipv4", None, None, None)),
            ("string", ["wkt"], ("geometry", None, None, None)),
            ("string", ["json"], ("json", None, None, None)),
            ("string", ["array(int)"], ("integer[]", None, None, None)),
            ("bytes", [], ("blob", None, None, None)),
            ("bytes", ["vector(3)"], ("vector(3)", None, None, None)),
            ("bytes", ["wkt"], ("geometry", None, None, None)),
            # JSON result-set datatype names come through the same function
            ("char32", [], ("varchar", 32, None, None)),
            ("timestamp", [], ("timestamp", None, None, None)),
            ("boolean", [], ("boolean", None, None, None)),
            ("mystery", [], ("mystery", None, None, None)),
        ],
    )
    def test_map(self, base, props, expected):
        assert map_kinetica_type(base, props) == expected

    def test_unbounded_sentinel_is_large(self):
        assert UNBOUNDED_STRING_SIZE > 256


class TestValueConverters:
    def test_timestamp_epoch_ms(self):
        conv = value_converter("timestamp")
        assert conv(86_400_000) == datetime.datetime(1970, 1, 2)

    def test_datetime_string(self):
        conv = value_converter("datetime")
        assert conv("2024-05-06 07:08:09.123") == datetime.datetime(2024, 5, 6, 7, 8, 9, 123000)
        assert conv("2024-05-06 07:08:09") == datetime.datetime(2024, 5, 6, 7, 8, 9)

    def test_date_and_time(self):
        assert value_converter("date")("2024-05-06") == datetime.date(2024, 5, 6)
        assert value_converter("time")("07:08:09.500") == datetime.time(7, 8, 9, 500000)

    def test_boolean_and_decimal(self):
        assert value_converter("boolean")(1) is True
        assert value_converter("boolean")(0) is False
        assert value_converter("decimal")("12.3400") == decimal.Decimal("12.3400")

    def test_no_converter_for_plain_types(self):
        assert value_converter("int") is None
        assert value_converter("string") is None
        assert value_converter("double") is None

    def test_unparseable_values_pass_through(self):
        assert value_converter("datetime")("not a date") == "not a date"


def test_split_qualified_name():
    assert split_qualified_name("s.t", "d") == ("s", "t")
    assert split_qualified_name("t", "d") == ("d", "t")
