{% macro kinetica__create_view_as(relation, sql) -%}
  {%- set sql_header = config.get('sql_header', none) -%}
  {%- set contract_config = config.get('contract') -%}

  {{ sql_header if sql_header is not none }}
  {%- if (contract_config is not none) and contract_config.enforced %}
    {{ get_assert_columns_equivalent(sql) }}
  {%- endif %}
  create or replace view {{ relation.render() }}
  as (
    {{ sql }}
  )
{%- endmacro %}


{% macro kinetica__get_replace_view_sql(relation, sql) -%}
    {{ kinetica__create_view_as(relation, sql) }}
{%- endmacro %}
