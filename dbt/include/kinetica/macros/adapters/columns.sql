{% macro kinetica__get_empty_subquery_sql(select_sql, select_sql_header=none) -%}
    {%- if select_sql_header is not none -%}
    {{ select_sql_header }}
    {%- endif -%}
    select * from (
        {{ select_sql }}
    ) as __dbt_sbq
    where 1 = 0
    limit 0
{%- endmacro %}


{#
  Kinetica ALTER TABLE grammar:
    ALTER TABLE t ADD <col> <definition>
    ALTER TABLE t DROP <col>
    ALTER TABLE t ALTER COLUMN <col> <definition>
    ALTER TABLE t RENAME COLUMN <col> TO <new>
  One action per statement; the cursor splits on ';'.
#}
{% macro kinetica__alter_column_type(relation, column_name, new_column_type) -%}
  {% call statement('alter_column_type') %}
    alter table {{ relation.render() }} alter column {{ adapter.quote(column_name) }} {{ new_column_type }}
  {% endcall %}
{% endmacro %}


{% macro kinetica__alter_relation_add_remove_columns(relation, add_columns, remove_columns) %}
  {% if add_columns is none %}{% set add_columns = [] %}{% endif %}
  {% if remove_columns is none %}{% set remove_columns = [] %}{% endif %}

  {% for column in add_columns %}
    {% call statement('add_column') %}
      alter table {{ relation.render() }} add {{ column.quoted }} {{ column.expanded_data_type }}
    {% endcall %}
  {% endfor %}

  {% for column in remove_columns %}
    {% call statement('drop_column') %}
      alter table {{ relation.render() }} drop {{ column.quoted }}
    {% endcall %}
  {% endfor %}
{% endmacro %}


{% macro kinetica__create_columns(relation, columns) %}
  {% for column in columns %}
    {% call statement() %}
      alter table {{ relation.render() }} add {{ adapter.quote(column.name) }} {{ column.expanded_data_type }}
    {% endcall %}
  {% endfor %}
{% endmacro %}
