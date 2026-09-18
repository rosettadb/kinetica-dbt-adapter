{#
  Verified on Kinetica 7.2.3:

  CREATE [OR REPLACE] [REPLICATED] [TEMP] TABLE <schema>.<table>
  AS ( <select> )
      [PARTITION BY ...] [TIER STRATEGY (...)] [USING TABLE PROPERTIES (...)]

  (for CREATE TABLE ... AS the option clauses come *after* the select; with an
  explicit column list they come after the column definitions)

  Temp tables keep their schema qualifier: Kinetica temp tables are ordinary
  tables with a TTL, and dbt references them fully qualified later on.
#}
{% macro kinetica__create_table_as(temporary, relation, sql) -%}
  {%- set sql_header = config.get('sql_header', none) -%}
  {%- set contract_config = config.get('contract') -%}
  {%- set enforce_contract = (contract_config is not none) and contract_config.enforced and (not temporary) -%}

  {{ sql_header if sql_header is not none }}

  {%- if enforce_contract %}
    {{ get_assert_columns_equivalent(sql) }}
    create or replace {{ kinetica__table_kind(temporary) }} {{ relation.render() }}
    {{ get_table_columns_and_constraints() }}
    {{ kinetica__table_options_clause() }};

    insert into {{ relation.render() }}
    {{ get_select_subquery(sql) }}
  {%- else %}
    create or replace {{ kinetica__table_kind(temporary) }} {{ relation.render() }}
    as (
      {{ sql }}
    )
    {{ kinetica__table_options_clause() }}
  {%- endif %}
{%- endmacro %}


{% macro kinetica__table_kind(temporary) -%}
  {%- if config.get('replicated', false) %}replicated {% endif -%}
  {%- if temporary %}temp {% endif -%}
  table
{%- endmacro %}


{% macro kinetica__table_options_clause() -%}
  {%- set partition_by = config.get('partition_by', none) -%}
  {%- set tier_strategy = config.get('tier_strategy', none) -%}
  {%- set ttl = config.get('ttl', none) -%}
  {%- set props = {} -%}
  {%- do props.update(config.get('table_properties', none) or {}) -%}
  {%- if ttl is not none -%}{%- do props.update({'ttl': ttl}) -%}{%- endif -%}

  {%- if partition_by %}
    partition by {{ partition_by }}
  {%- endif %}
  {%- if tier_strategy %}
    tier strategy ( {{ tier_strategy }} )
  {%- endif %}
  {%- if props %}
    using table properties (
      {%- for key, value in props.items() %} {{ key }} = {{ value }}{{ ',' if not loop.last }}{% endfor %} )
  {%- endif %}
{%- endmacro %}
