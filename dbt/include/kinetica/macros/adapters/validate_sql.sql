{% macro kinetica__validate_sql(sql) -%}
  {% call statement('validate_sql') -%}
    explain {{ sql }}
  {% endcall %}
  {{ return(load_result('validate_sql')) }}
{% endmacro %}
