{% macro kinetica__get_batch_size() -%}
  {{ return(5000) }}
{%- endmacro %}


{#
  Kinetica's SQL endpoint has no pyformat-style parameter binding, so seed rows
  are rendered as literals (adapter.render_literal handles quoting/escaping).
#}
{% macro kinetica__load_csv_rows(model, agate_table) %}
  {% set batch_size = get_batch_size() %}
  {% set cols_sql = get_seed_column_quoted_csv(model, agate_table.column_names) %}
  {% set statements = [] %}

  {% for chunk in agate_table.rows | batch(batch_size) %}
      {% set sql %}
          insert into {{ this.render() }} ({{ cols_sql }}) values
          {% for row in chunk -%}
              ({%- for value in row -%}
                  {{ adapter.render_literal(value) }}
                  {%- if not loop.last %},{% endif %}
              {%- endfor -%})
              {%- if not loop.last %},{% endif %}
          {%- endfor %}
      {% endset %}

      {% do adapter.add_query(sql, abridge_sql_log=True) %}

      {% if loop.index0 == 0 %}
          {% do statements.append(sql) %}
      {% endif %}
  {% endfor %}

  {{ return(statements[0]) }}
{% endmacro %}
