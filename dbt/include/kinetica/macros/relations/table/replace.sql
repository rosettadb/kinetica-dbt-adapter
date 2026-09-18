{% macro kinetica__get_replace_table_sql(relation, sql) -%}
    {{ kinetica__create_table_as(False, relation, sql) }}
{%- endmacro %}
