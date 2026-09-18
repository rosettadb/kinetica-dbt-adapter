import json
from typing import Dict, List

import pytest
from gpudb import GPUdbException

from dbt.adapters.kinetica.client import (
    KineticaCursor,
    KineticaHandle,
    KineticaQueryResult,
    decode_json_result,
)


def _payload(headers, datatypes, columns):
    body = {"column_headers": headers, "column_datatypes": datatypes}
    for i, values in enumerate(columns, start=1):
        body[f"column_{i}"] = values
    return json.dumps(body)


class TestDecodeJson:
    def test_empty_payloads(self):
        assert decode_json_result(None) == ([], [])
        assert decode_json_result("") == ([], [])
        assert decode_json_result("{}") == ([], [])
        assert decode_json_result("not json") == ([], [])

    def test_rows_and_conversion(self):
        payload = _payload(
            ["id", "name", "ts", "flag"],
            ["int", "char16", "timestamp", "boolean"],
            [[1, 2], ["a", None], [0, 86_400_000], [1, 0]],
        )
        columns, rows = decode_json_result(payload)
        assert columns == [("id", "int"), ("name", "char16"), ("ts", "timestamp"), ("flag", "boolean")]
        assert rows[0][0] == 1 and rows[0][1] == "a" and rows[0][3] is True
        assert rows[1][1] is None and rows[1][2].day == 2 and rows[1][3] is False

    def test_zero_rows_still_reports_columns(self):
        columns, rows = decode_json_result(_payload(["x"], ["double"], [[]]))
        assert columns == [("x", "double")]
        assert rows == []


class FakeHandle:
    """Scripted stand-in for KineticaHandle.execute_sql."""

    def __init__(self, page_size=2):
        self.page_size = page_size
        self.calls: List[Dict] = []
        self.cleared: List[str] = []
        self.rows_by_statement: Dict[str, List[tuple]] = {}
        self.columns_by_statement: Dict[str, List[tuple]] = {}
        self.fail_on: Dict[str, str] = {}

    def script_query(self, statement, columns, rows):
        self.columns_by_statement[statement] = columns
        self.rows_by_statement[statement] = rows

    def execute_sql(self, statement, offset=0, limit=None, options=None):
        self.calls.append({"statement": statement, "offset": offset, "limit": limit, "options": dict(options or {})})
        if statement in self.fail_on:
            raise GPUdbException(self.fail_on[statement])
        if statement not in self.rows_by_statement:
            # DDL / DML
            return KineticaQueryResult(count_affected=7)
        all_rows = self.rows_by_statement[statement]
        page = all_rows[offset : offset + limit]
        has_more = offset + limit < len(all_rows)
        return KineticaQueryResult(
            columns=self.columns_by_statement[statement],
            rows=page,
            total_number_of_records=len(all_rows),
            has_more_records=has_more,
            paging_table=(options or {}).get("paging_table", "") if has_more else "",
        )

    def clear_table(self, table_name):
        self.cleared.append(table_name)


class TestCursor:
    def test_ddl_sets_rowcount_and_no_description(self):
        handle = FakeHandle()
        cur = KineticaCursor(handle)
        cur.execute("create table t as (select 1)")
        assert cur.description is None
        assert cur.rowcount == 7
        assert cur.statement_kind == "CREATE"
        assert "paging_table" not in handle.calls[0]["options"]

    def test_multi_statement_keeps_last_result(self):
        handle = FakeHandle()
        handle.script_query("select 2", [("v", "int")], [(2,)])
        cur = KineticaCursor(handle)
        cur.execute("drop table if exists x; select 2")
        assert [c["statement"] for c in handle.calls] == ["drop table if exists x", "select 2"]
        assert cur.description[0][0] == "v"
        assert cur.fetchall() == [(2,)]

    def test_transaction_control_is_skipped(self):
        handle = FakeHandle()
        cur = KineticaCursor(handle)
        cur.execute("BEGIN; commit; rollback")
        assert handle.calls == []

    def test_paging_fetchall(self):
        handle = FakeHandle(page_size=2)
        rows = [(i,) for i in range(5)]
        handle.script_query("select i from t", [("i", "int")], rows)
        cur = KineticaCursor(handle)
        cur.execute("select i from t")
        assert cur.rowcount == 5
        assert cur.fetchall() == rows
        # first page + two more pages
        assert [c["offset"] for c in handle.calls] == [0, 2, 4]
        # paging table requested on the first call and reused afterwards
        first_opts = handle.calls[0]["options"]
        assert first_opts["paging_table"].startswith("dbt_paging_")
        assert handle.calls[1]["options"]["paging_table"] == first_opts["paging_table"]
        # cleaned up once exhausted
        assert handle.cleared == [first_opts["paging_table"]]

    def test_fetch_limit_caps_pages(self):
        handle = FakeHandle(page_size=2)
        rows = [(i,) for i in range(10)]
        handle.script_query("select i from t", [("i", "int")], rows)
        cur = KineticaCursor(handle)
        cur.execute("select i from t", limit=3)
        assert cur.fetchall() == rows[:3]
        assert [c["limit"] for c in handle.calls] == [2, 1]

    def test_fetchmany_and_fetchone(self):
        handle = FakeHandle(page_size=2)
        rows = [(i,) for i in range(5)]
        handle.script_query("select i from t", [("i", "int")], rows)
        cur = KineticaCursor(handle)
        cur.execute("select i from t")
        assert cur.fetchmany(3) == rows[:3]
        assert cur.fetchone() == (3,)
        assert cur.fetchall() == [(4,)]
        assert cur.fetchone() is None

    def test_bindings_are_rendered_as_literals(self):
        handle = FakeHandle()
        cur = KineticaCursor(handle)
        cur.execute("insert into t values (%s, %s)", ["x'y", None])
        assert handle.calls[0]["statement"] == "insert into t values ('x''y', NULL)"

    def test_errors_propagate(self):
        handle = FakeHandle()
        handle.fail_on["select boom"] = "[ERROR]: nope"
        cur = KineticaCursor(handle)
        with pytest.raises(GPUdbException):
            cur.execute("select boom")


class TestHandle:
    def test_execute_sql_translates_response(self):
        class FakeDb:
            def execute_sql(self, statement, offset, limit, encoding, options):
                assert encoding == "json"
                assert options == {"ttl": "5", "extra": "true"}
                return {
                    "status_info": {"status": "OK"},
                    "json_encoded_response": _payload(["a"], ["long"], [[1, 2]]),
                    "total_number_of_records": 2,
                    "has_more_records": False,
                    "count_affected": 0,
                    "paging_table": "",
                    "info": {"result_table_list": "t1,t2"},
                }

        handle = KineticaHandle(FakeDb(), base_options={"ttl": 5}, page_size=100)
        result = handle.execute_sql("select 1", options={"extra": True})
        assert result.rows == [(1,), (2,)]
        assert result.columns == [("a", "long")]
        assert result.result_table_list == ["t1", "t2"]

    def test_error_status_raises(self):
        class FakeDb:
            def execute_sql(self, **kwargs):
                return {"status_info": {"status": "ERROR", "message": "table not found"}}

        handle = KineticaHandle(FakeDb())
        with pytest.raises(GPUdbException) as exc:
            handle.execute_sql("select * from nope")
        assert "table not found" in str(exc.value)

    def test_close_is_idempotent(self):
        class FakeDb:
            exits = 0

            def __exit__(self, *args):
                FakeDb.exits += 1

        handle = KineticaHandle(FakeDb())
        assert handle.closed is False
        handle.close()
        handle.close()
        assert handle.closed is True
        assert FakeDb.exits == 1
        handle.commit()
        handle.rollback()
