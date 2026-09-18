# dbt-kinetica

A [dbt](https://www.getdbt.com/) adapter for [Kinetica](https://www.kinetica.com/).

It talks to Kinetica through the official `gpudb` Python client (`/execute/sql`,
`/show/table`, `/show/schema`), so no ODBC/JDBC driver is needed.

| Component      | Version tested |
| -------------- | -------------- |
| dbt-core       | 1.12           |
| dbt-adapters   | 1.24           |
| gpudb (client) | 7.2            |
| Python         | 3.9 - 3.12     |

## Status

Alpha. The Python layer and the macros are covered by unit tests and by an
end-to-end "dry run" that pushes seeds, models, tests, snapshots and
`docs generate` through the real dbt engine against an in-memory fake server.
The generated SQL has **not yet been executed against a live Kinetica cluster**;
see [Verifying against a real server](#verifying-against-a-real-server) before
relying on it.

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install .                   # or: pip install -e ".[dev]"
```

## Profile

```yaml
my_profile:
  target: dev
  outputs:
    dev:
      type: kinetica
      host: http://localhost:9191        # full URL of the head node (alias: url)
      user: admin                         # alias: username
      password: "{{ env_var('KINETICA_PASSWORD') }}"   # alias: pass
      schema: ki_home                     # default schema for models
      threads: 4

      # optional
      database: kinetica                  # label only; Kinetica has no databases
      timeout: 600                        # seconds per HTTP request (default: no limit)
      retries: 1                          # connection open retries
      skip_ssl_cert_verification: false
      disable_auto_discovery: true        # keep true behind docker/NAT/load balancers
      disable_failover: false
      oauth_token: null
      page_size: 10000                    # rows fetched per page for query results
      http_headers: {}
      sql_options:                        # forwarded to every /execute/sql call
        ttl: "120"
```

`dbt init` prompts for the required fields (see `profile_template.yml`).

## Model configuration

| Config                 | Applies to         | Effect                                                                 |
| ---------------------- | ------------------ | ---------------------------------------------------------------------- |
| `materialized`         | all                | `table`, `view`, `incremental`, `materialized_view`, `ephemeral`, `seed`, `snapshot` |
| `replicated: true`     | table, incremental | `CREATE REPLICATED TABLE`                                              |
| `ttl: <minutes>`       | table, incremental | added to `USING TABLE PROPERTIES (ttl = n)`                            |
| `table_properties: {}` | table, incremental | free-form `USING TABLE PROPERTIES (k = v, ...)`                        |
| `partition_by: "..."`  | table, incremental | raw `PARTITION BY ...` clause, passed through verbatim                 |
| `tier_strategy: "..."` | table, incremental | raw `TIER STRATEGY ( ... )` clause                                     |
| `indexes: [...]`       | table, incremental, seed, snapshot | `[{columns: [a], type: geospatial}]` -> `CREATE [type] INDEX ON t (a)` |
| `refresh: "..."`       | materialized_view  | e.g. `EVERY 5 MINUTES`, `ON CHANGE`, `ON QUERY`, `MANUAL`              |
| `incremental_strategy` | incremental        | `append` (default), `delete+insert`, `microbatch`                      |
| `unique_key`           | incremental        | string or list; lists are compared through a concatenated key          |
| `grants`               | all                | `GRANT <priv> ON TABLE <rel> TO <grantee>`; never revokes              |

Example:

```sql
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='order_id',
    ttl=1440,
    indexes=[{'columns': ['customer_id']}]
) }}
select ... from {{ ref('stg_orders') }}
{% if is_incremental() %}
where order_date >= (select max(order_date) from {{ this }})
{% endif %}
```

## How it maps dbt onto Kinetica

* **No transactions.** Kinetica auto-commits. `BEGIN`/`COMMIT`/`ROLLBACK` are
  never sent, and hooks run as plain statements.
* **Tables and views are replaced in place** with `CREATE OR REPLACE`; there is
  no intermediate/backup relation and no rename. Materialized views are
  replaced on `--full-refresh` and otherwise `REFRESH MATERIALIZED VIEW`ed.
* **Incremental** models stage rows in a schema-qualified `TEMP` table
  (`<model>__dbt_tmp`) which is dropped at the end of the run.
  `delete+insert` is `DELETE ... WHERE key IN (SELECT DISTINCT key FROM tmp)` followed by
  `INSERT ... SELECT`. `merge` and `insert_overwrite` raise a clear error
  because Kinetica has no `MERGE`.
* **Snapshots** use `UPDATE ... FROM` + `INSERT ... SELECT` instead of `MERGE`,
  `NOW()` as the snapshot time and `MD5(CONCAT(...))` for `dbt_scd_id`.
* **Seeds** are inserted as literal `VALUES` batches (5000 rows per statement).
  Inferred types: `bigint`, `double`, `varchar`, `boolean`, `date`, `datetime`, `time`.
* **Metadata** (schemas, relations, columns, catalog) comes from the native
  `/show/schema` and `/show/table` endpoints, not from SQL against a catalog.
  Kinetica types are mapped to `integer`, `bigint`, `tinyint`, `smallint`,
  `real`, `double`, `decimal(p,s)`, `varchar[(n)]`, `date`, `time`, `datetime`,
  `timestamp`, `boolean`, `blob`, `json`, `geometry`, `uuid`, `ipv4`,
  `vector(n)`, `type[]`.
* **Multi-statement blocks** emitted by dbt macros are split on `;` (outside
  quotes and comments) and sent one statement per `/execute/sql` call.
* **Large result sets** are paged with Kinetica paging tables that are cleared
  once consumed (and expire after 20 minutes regardless).
* **Cross-database macros**: `dateadd` -> `TIMESTAMPADD`, `datediff` ->
  `TIMESTAMPDIFF`, `date_trunc(UNIT, x)`, `split_part` -> `SPLIT`, `hash` ->
  `MD5`, `concat` -> nested `CONCAT`, `bool_or` -> `MAX(CASE ...)`,
  `any_value` -> `MIN`, `listagg` -> `STRING_AGG`, `last_day` (month) -> `LAST_DAY`.

### Not supported

* `persist_docs` (no `COMMENT ON` in Kinetica): logged and skipped.
* `merge` / `insert_overwrite` incremental strategies.
* Renaming views or materialized views.
* Source freshness via table metadata (`loaded_at_field` queries work).
* Python models.

## Verifying against a real server

Several statements rely on Kinetica syntax that could only be checked against
documentation, not a running cluster. When you first point this adapter at a
real Kinetica (7.1+ recommended), watch these in particular and open an issue
or adjust the macro if one fails:

| Statement / function                                         | Macro                                            |
| ------------------------------------------------------------ | ------------------------------------------------ |
| `CREATE OR REPLACE [REPLICATED] [TEMP] TABLE ... AS (...)`    | `kinetica__create_table_as`                      |
| `USING TABLE PROPERTIES (...)` placed before `AS`             | `kinetica__table_options_clause`                 |
| `CREATE OR REPLACE VIEW`, `CREATE OR REPLACE MATERIALIZED VIEW ... REFRESH ...` | `relations/view`, `relations/materialized_view` |
| `REFRESH MATERIALIZED VIEW <name>`                            | `kinetica__refresh_materialized_view`            |
| `ALTER TABLE t ADD <col> <type>` / `DROP <col>` / `ALTER COLUMN` | `macros/adapters/columns.sql`                  |
| `UPDATE t AS a SET ... FROM s AS b WHERE ...`                  | `kinetica__snapshot_merge_sql`                   |
| `MD5()`, `STRING_AGG()`, `SPLIT()`, `TIMESTAMPADD/DIFF`, `DATE_TRUNC(UNIT, x)` | `macros/utils/utils.sql`             |
| `GRANT <priv> ON TABLE <rel> TO <grantee>`                    | `macros/adapters/grants.sql`                     |
| Leading `/* {...} */` query-comment blocks                    | disable with `query-comment: null` in `dbt_project.yml` if rejected |

Every one of these lives in a single dispatched macro under
`dbt/include/kinetica/macros`, so a project-level override
(`{% macro kinetica__... %}` in your own `macros/`) is enough to patch it.

Run the official adapter test-suite against your cluster:

```bash
pip install -e ".[dev]"
set KINETICA_HOST=http://localhost:9191
set KINETICA_USER=admin
set KINETICA_PASSWORD=...
pytest tests/functional -q
```

Without `KINETICA_HOST` the functional tests are skipped and only the unit
tests (`pytest tests/unit -q`) run.

## Example project

`examples/demo` is a small project (seeds, staging views, a table with
`ttl`, a `delete+insert` incremental model, generic + singular tests and a
`check` snapshot):

```bash
cd examples/demo
set KINETICA_HOST=http://localhost:9191
dbt seed   --profiles-dir .
dbt run    --profiles-dir .
dbt test   --profiles-dir .
dbt snapshot --profiles-dir .
```

## Repository layout

```
dbt/adapters/kinetica/
  connections.py   credentials + connection manager (no-op transactions)
  client.py        GPUdb wrapper with a DB-API-style cursor, paging, JSON decoding
  impl.py          adapter: metadata via /show/*, catalog, incremental strategies
  column.py        Kinetica-aware Column (unbounded varchar, decimal(p,s), ...)
  relation.py      Relation with no database component; tables renameable, views replaceable
  sql_utils.py     statement splitting, literal rendering, type mapping
dbt/include/kinetica/macros/
  adapters/        schema, relation, columns, grants, hooks, indexes, timestamps
  relations/       table / view / materialized view DDL
  materializations/ table, view, incremental (+strategies), seed, snapshot, tests
  utils/           cross-database macro overrides and type names
tests/unit/        pure unit tests + dbt dry run against an in-memory fake server
tests/functional/  dbt-tests-adapter suite (needs KINETICA_HOST)
examples/demo/     sample dbt project
```

## License

Apache-2.0
