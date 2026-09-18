{#
  Model config:
    indexes:
      - columns: [col_a]
      - columns: [geo_col]
        type: geospatial
  Renders (verified on Kinetica 7.2.3):
    ALTER TABLE <table> ADD [<type>] INDEX (<columns>)
#}
{% macro kinetica__get_create_index_sql(relation, index_dict) -%}
  {%- set columns = index_dict.get('columns', []) -%}
  {%- set index_type = index_dict.get('type') -%}
  {%- if columns | length == 0 -%}
    {{ return(none) }}
  {%- endif -%}
  {%- set quoted = [] -%}
  {%- for col in columns -%}{%- do quoted.append(adapter.quote(col)) -%}{%- endfor -%}
  alter table {{ relation.render() }} add {% if index_type %}{{ index_type }} {% endif %}index ({{ quoted | join(', ') }})
{%- endmacro %}
