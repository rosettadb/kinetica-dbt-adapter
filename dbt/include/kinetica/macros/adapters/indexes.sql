{#
  Model config:
    indexes:
      - columns: [col_a]
      - columns: [geo_col]
        type: geospatial
  Renders: CREATE [<type>] INDEX ON <table> (<columns>)
#}
{% macro kinetica__get_create_index_sql(relation, index_dict) -%}
  {%- set columns = index_dict.get('columns', []) -%}
  {%- set index_type = index_dict.get('type') -%}
  {%- if columns | length == 0 -%}
    {{ return(none) }}
  {%- endif -%}
  {%- set quoted = [] -%}
  {%- for col in columns -%}{%- do quoted.append(adapter.quote(col)) -%}{%- endfor -%}
  create {% if index_type %}{{ index_type }} {% endif %}index on {{ relation.render() }} ({{ quoted | join(', ') }})
{%- endmacro %}
