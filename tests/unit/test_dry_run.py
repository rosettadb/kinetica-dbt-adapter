"""End-to-end 'dry run' of the adapter through the real dbt engine.

``KineticaHandle.from_credentials`` is replaced with an in-memory fake that
records every SQL statement and keeps a tiny catalog, so materializations,
seeds, snapshots and tests all execute their Jinja against real dbt without a
server.  This catches macro/runtime errors and lets us assert on the SQL that
Kinetica would receive."""

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

import pytest
from dbt.tests.util import run_dbt

from dbt.adapters.kinetica import client as client_module
from dbt.adapters.kinetica.client import KineticaCursor, KineticaQueryResult
from dbt.adapters.kinetica.sql_utils import first_keyword, strip_sql_comments

DEFAULT_COLUMNS: List[Tuple[str, str, List[str]]] = [
    ("id", "int", ["data"]),
    ("name", "string", ["char16", "nullable"]),
    ("updated_at", "string", ["datetime", "nullable"]),
]
SNAPSHOT_COLUMNS: List[Tuple[str, str, List[str]]] = [
    ("dbt_scd_id", "string", ["char32"]),
    ("dbt_updated_at", "string", ["datetime", "nullable"]),
    ("dbt_valid_from", "string", ["datetime", "nullable"]),
    ("dbt_valid_to", "string", ["datetime", "nullable"]),
]

_IDENT = r'"?([A-Za-z0-9_]+)"?'
_CREATE_RE = re.compile(
    r"create\s+(?:or\s+replace\s+)?(?:replicated\s+)?(?:temp\s+)?(table|view|materialized\s+view)\s+"
    + _IDENT + r"\." + _IDENT,
    re.IGNORECASE,
)
_DROP_RE = re.compile(
    r"drop\s+(table|view|materialized\s+view)\s+if\s+exists\s+" + _IDENT + r"\." + _IDENT,
    re.IGNORECASE,
)
_RENAME_RE = re.compile(
    r"alter\s+table\s+" + _IDENT + r"\." + _IDENT + r"\s+rename\s+to\s+" + _IDENT, re.IGNORECASE
)
_SCHEMA_RE = re.compile(r"(create|drop)\s+schema\s+if\s+(?:not\s+)?exists\s+" + _IDENT, re.IGNORECASE)


class FakeKinetica:
    """Shared in-memory 'server' (one per test class)."""

    def __init__(self):
        self.statements: List[str] = []
        self.schemas: set = set()
        # (schema, table) -> {"kind": ..., "columns": [...]}
        self.tables: Dict[Tuple[str, str], Dict] = {}

    # --- catalog maintenance -------------------------------------------- #
    def _apply_ddl(self, statement: str) -> None:
        body = strip_sql_comments(statement)
        m = _SCHEMA_RE.search(body)
        if m:
            if m.group(1).lower() == "create":
                self.schemas.add(m.group(2))
            else:
                self.schemas.discard(m.group(2))
                for key in [k for k in self.tables if k[0] == m.group(2)]:
                    del self.tables[key]
            return
        m = _CREATE_RE.search(body)
        if m:
            kind = " ".join(m.group(1).lower().split())
            columns = list(DEFAULT_COLUMNS)
            if "dbt_scd_id" in body:
                columns += SNAPSHOT_COLUMNS
            self.tables[(m.group(2), m.group(3))] = {"kind": kind, "columns": columns}
            return
        m = _DROP_RE.search(body)
        if m:
            self.tables.pop((m.group(2), m.group(3)), None)
            return
        m = _RENAME_RE.search(body)
        if m:
            entry = self.tables.pop((m.group(1), m.group(2)), None)
            if entry is not None:
                self.tables[(m.group(1), m.group(3))] = entry
            return

    # --- fake results ----------------------------------------------------- #
    def _query_result(self, statement: str) -> KineticaQueryResult:
        body = strip_sql_comments(statement).lower()
        if "as failures" in body:
            return KineticaQueryResult(
                columns=[("failures", "long"), ("should_warn", "int"), ("should_error", "int")],
                rows=[(0, 0, 0)],
                total_number_of_records=1,
            )
        if "dbt_snapshot_time" in body:
            return KineticaQueryResult(
                columns=[("dbt_snapshot_time", "datetime")], rows=[], total_number_of_records=0
            )
        if "where 1 = 0" in body or "limit 0" in body:
            cols = [(name, dtype if dtype != "string" else (props[0] if props else "string"))
                    for name, dtype, props in DEFAULT_COLUMNS]
            if "dbt_scd_id" in body or "dbt_updated_at" in body:
                cols += [(name, props[0]) for name, dtype, props in SNAPSHOT_COLUMNS]
            return KineticaQueryResult(columns=cols, rows=[], total_number_of_records=0)
        if "count(*)" in body:
            return KineticaQueryResult(columns=[("count", "long")], rows=[(0,)], total_number_of_records=1)
        return KineticaQueryResult(columns=[("id", "int")], rows=[(1,)], total_number_of_records=1)


class FakeHandle:
    page_size = 1000

    def __init__(self, server: FakeKinetica):
        self.server = server
        self._closed = False

    def cursor(self):
        return KineticaCursor(self)

    @property
    def closed(self):
        return self._closed

    def close(self):
        self._closed = True

    def commit(self):
        pass

    def rollback(self):
        pass

    def clear_table(self, table_name):
        pass

    def execute_sql(self, statement, offset=0, limit=None, options=None):
        self.server.statements.append(statement)
        kind = first_keyword(statement)
        if kind in ("select", "with", "(", "explain", "show"):
            return self.server._query_result(statement)
        self.server._apply_ddl(statement)
        return KineticaQueryResult(count_affected=1)

    def show_schema(self, schema_name, options=None):
        if schema_name == "":
            names = sorted(self.server.schemas)
        else:
            names = [schema_name] if schema_name in self.server.schemas else []
        return {"status_info": {"status": "OK"}, "schema_names": names, "schema_tables": [[] for _ in names]}

    def show_table(self, table_name, options=None):
        options = options or {}
        entries = []
        if options.get("show_children") == "true":
            for (schema, table), entry in self.server.tables.items():
                if schema == table_name:
                    entries.append((f"{schema}.{table}", entry))
        else:
            schema, _, table = table_name.partition(".")
            entry = self.server.tables.get((schema, table))
            if entry:
                entries.append((table_name, entry))

        descriptions = {
            "table": [],
            "view": ["LOGICAL_VIEW", "VIEW"],
            "materialized view": ["MATERIALIZED_VIEW", "VIEW"],
        }
        return {
            "status_info": {"status": "OK"},
            "table_names": [name for name, _ in entries],
            "table_descriptions": [descriptions[e["kind"]] for _, e in entries],
            "type_schemas": [
                json.dumps(
                    {
                        "type": "record",
                        "name": "type_name",
                        "fields": [{"name": n, "type": [t, "null"]} for n, t, _ in e["columns"]],
                    }
                )
                for _, e in entries
            ],
            "properties": [{n: p for n, _, p in e["columns"]} for _, e in entries],
            "additional_info": [{} for _ in entries],
        }


@pytest.fixture(scope="class")
def fake_server():
    return FakeKinetica()


@pytest.fixture(scope="class", autouse=True)
def _patch_handle(fake_server):
    mp = pytest.MonkeyPatch()
    mp.setattr(
        client_module.KineticaHandle,
        "from_credentials",
        classmethod(lambda cls, credentials: FakeHandle(fake_server)),
    )
    yield
    mp.undo()


@pytest.fixture(scope="class")
def dbt_profile_target():
    return {"type": "kinetica", "threads": 1, "host": "http://fake-kinetica:9191", "user": "u", "password": "p"}


def _statements_matching(server: FakeKinetica, pattern: str) -> List[str]:
    rx = re.compile(pattern, re.IGNORECASE | re.DOTALL)
    return [s for s in server.statements if rx.search(strip_sql_comments(s))]


MODEL_TABLE = """
{{ config(materialized='table') }}
select 1 as id, 'a' as name, cast('2024-01-01 00:00:00' as datetime) as updated_at
"""
MODEL_VIEW = "select * from {{ ref('my_table') }}"
MODEL_INCREMENTAL = """
{{ config(materialized='incremental', incremental_strategy='delete+insert', unique_key='id') }}
select * from {{ ref('my_table') }}
{% if is_incremental() %} where updated_at > (select max(updated_at) from {{ this }}) {% endif %}
"""
MODEL_INCREMENTAL_COMPOSITE = """
{{ config(materialized='incremental', incremental_strategy='delete+insert', unique_key=['id', 'name']) }}
select * from {{ ref('my_table') }}
"""
MODEL_INCREMENTAL_APPEND = """
{{ config(materialized='incremental') }}
select * from {{ ref('my_table') }}
"""
MODEL_MV = """
{{ config(materialized='materialized_view', refresh='EVERY 5 MINUTES') }}
select * from {{ ref('my_table') }}
"""
MODEL_WITH_OPTIONS = """
{{ config(materialized='table', replicated=true, ttl=30, table_properties={'chunk size': 100000},
          indexes=[{'columns': ['id']}], grants={'select': ['analyst']}) }}
select * from {{ ref('my_table') }}
"""
SCHEMA_YML = """
version: 2
models:
  - name: my_table
    columns:
      - name: id
        data_tests: [unique, not_null]
      - name: name
        data_tests:
          - accepted_values:
              arguments:
                values: ['a', 'b']
  - name: my_view
    columns:
      - name: id
        data_tests:
          - relationships:
              arguments:
                to: ref('my_table')
                field: id
"""
SEED_CSV = """id,name,updated_at
1,it's,2024-01-01 10:00:00
2,,2024-01-02 11:30:00
"""
SNAPSHOT_TS = """
{% snapshot snap_ts %}
{{ config(unique_key='id', strategy='timestamp', updated_at='updated_at') }}
select * from {{ ref('my_table') }}
{% endsnapshot %}
"""
SNAPSHOT_CHECK = """
{% snapshot snap_check %}
{{ config(unique_key='id', strategy='check', check_cols=['name']) }}
select * from {{ ref('my_table') }}
{% endsnapshot %}
"""


class TestDryRun:
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "my_table.sql": MODEL_TABLE,
            "my_view.sql": MODEL_VIEW,
            "my_incremental.sql": MODEL_INCREMENTAL,
            "my_incremental_composite.sql": MODEL_INCREMENTAL_COMPOSITE,
            "my_incremental_append.sql": MODEL_INCREMENTAL_APPEND,
            "my_mv.sql": MODEL_MV,
            "my_options.sql": MODEL_WITH_OPTIONS,
            "schema.yml": SCHEMA_YML,
        }

    @pytest.fixture(scope="class")
    def seeds(self):
        return {"my_seed.csv": SEED_CSV}

    @pytest.fixture(scope="class")
    def snapshots(self):
        return {"snap_ts.sql": SNAPSHOT_TS, "snap_check.sql": SNAPSHOT_CHECK}

    def test_full_flow(self, project, fake_server):
        schema = project.test_schema

        # ---- seed ---------------------------------------------------------- #
        results = run_dbt(["seed"])
        assert len(results) == 1
        inserts = _statements_matching(fake_server, r"insert into .*my_seed")
        assert inserts, "seed insert not issued"
        assert "'it''s'" in inserts[0]
        assert "NULL" in inserts[0]
        creates = _statements_matching(fake_server, r'create table "%s"."my_seed"' % schema)
        assert creates and '"id" bigint' in creates[0] and '"updated_at" datetime' in creates[0]

        # ---- first run: everything gets created -------------------------- #
        results = run_dbt(["run"])
        assert len(results) == 7
        assert all(r.status == "success" for r in results)

        table_sql = _statements_matching(fake_server, r'create or replace table "%s"."my_table"' % schema)
        assert table_sql and " as (" in table_sql[0].lower()

        view_sql = _statements_matching(fake_server, r'create or replace view "%s"."my_view"' % schema)
        assert view_sql

        mv_sql = _statements_matching(fake_server, r'create materialized view "%s"."my_mv"' % schema)
        assert mv_sql and "refresh EVERY 5 MINUTES" in mv_sql[0]

        options_sql = _statements_matching(fake_server, r'create or replace replicated table "%s"."my_options"' % schema)
        assert options_sql
        assert "using table properties" in options_sql[0]
        assert "chunk size = 100000" in options_sql[0]
        assert "ttl = 30" in options_sql[0]
        assert _statements_matching(fake_server, r'alter table "%s"."my_options" add index \("id"\)' % schema)
        assert _statements_matching(fake_server, r'grant select on table "%s"."my_options" to analyst' % schema)

        # first incremental run builds the table directly
        assert _statements_matching(fake_server, r'create or replace table "%s"."my_incremental"\s+as' % schema)
        assert not _statements_matching(fake_server, r"delete from .*my_incremental")

        # no transaction statements ever reach the server
        assert not _statements_matching(fake_server, r"^\s*(begin|commit|rollback)\b")

        # ---- second run: incremental strategies kick in -------------------- #
        fake_server.statements.clear()
        results = run_dbt(["run"])
        assert all(r.status == "success" for r in results)

        temp = _statements_matching(fake_server, r'create or replace temp table "%s"."my_incremental__dbt_tmp"' % schema)
        assert temp
        deletes = _statements_matching(fake_server, r'delete from "%s"."my_incremental"\s+where id in' % schema)
        assert deletes
        assert _statements_matching(fake_server, r'insert into "%s"."my_incremental" \("id", "name", "updated_at"\)' % schema)
        assert _statements_matching(fake_server, r'drop table if exists "%s"."my_incremental__dbt_tmp"' % schema)

        composite = _statements_matching(fake_server, r'delete from "%s"."my_incremental_composite"' % schema)
        assert composite and "concat(coalesce(cast(id as varchar), ''), concat('||', coalesce(cast(name as varchar), '')))" in composite[0]

        append = _statements_matching(fake_server, r'insert into "%s"."my_incremental_append"' % schema)
        assert append
        assert not _statements_matching(fake_server, r'delete from "%s"."my_incremental_append"' % schema)

        # existing table/view/mv are replaced in place, never renamed
        assert _statements_matching(fake_server, r'create or replace table "%s"."my_table"' % schema)
        assert _statements_matching(fake_server, r'create or replace view "%s"."my_view"' % schema)
        assert _statements_matching(fake_server, r'refresh materialized view "%s"."my_mv"' % schema)
        assert not _statements_matching(fake_server, r"rename to")

        # ---- full refresh of the incremental model -------------------------- #
        fake_server.statements.clear()
        results = run_dbt(["run", "--select", "my_incremental", "--full-refresh"])
        assert results[0].status == "success"
        assert _statements_matching(fake_server, r'create or replace table "%s"."my_incremental"\s+as' % schema)
        assert not _statements_matching(fake_server, r"delete from")

        # ---- tests ---------------------------------------------------------- #
        fake_server.statements.clear()
        results = run_dbt(["test"])
        assert len(results) == 4
        assert all(r.status == "pass" for r in results)
        test_sql = _statements_matching(fake_server, r"as failures")
        assert test_sql and "case when count(*) != 0 then 1 else 0 end as should_warn" in test_sql[0]

        # ---- snapshots ------------------------------------------------------ #
        fake_server.statements.clear()
        results = run_dbt(["snapshot"])
        assert len(results) == 2 and all(r.status == "success" for r in results)
        first_snapshot = _statements_matching(fake_server, r'create or replace table "%s"."snap_ts"' % schema)
        assert first_snapshot and "sha256(" in first_snapshot[0]
        assert "concat(coalesce(cast(id as varchar), ''), concat('|', coalesce(cast(updated_at as varchar), '')))" in first_snapshot[0]

        fake_server.statements.clear()
        results = run_dbt(["snapshot"])
        assert all(r.status == "success" for r in results)
        staging = _statements_matching(fake_server, r'create or replace temp table "%s"."snap_ts__dbt_tmp"' % schema)
        assert staging
        update = _statements_matching(fake_server, r'update "%s"."snap_ts"\s+set dbt_valid_to' % schema)
        assert update and 'from "%s"."snap_ts", "%s"."snap_ts__dbt_tmp" as DBT_INTERNAL_SOURCE' % (schema, schema) in update[0]
        assert '"snap_ts".dbt_scd_id' in update[0]
        assert _statements_matching(fake_server, r'insert into "%s"."snap_ts" \(' % schema)
        assert _statements_matching(fake_server, r'drop table if exists "%s"."snap_ts__dbt_tmp"' % schema)

        # ---- docs generate uses the native catalog path ---------------------- #
        fake_server.statements.clear()
        run_dbt(["docs", "generate"])
        catalog_path = Path(str(project.project_root)) / "target" / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        node_keys = set(catalog["nodes"].keys())
        assert "model.test.my_table" in node_keys
        assert "seed.test.my_seed" in node_keys
        columns = catalog["nodes"]["model.test.my_table"]["columns"]
        assert columns["name"]["type"] == "varchar(16)"
        assert catalog["nodes"]["model.test.my_view"]["metadata"]["type"] == "VIEW"
