{% macro kinetica__create_schema(relation) -%}
  {%- call statement('create_schema') -%}
    create schema if not exists {{ relation.without_identifier().render() }}
  {%- endcall -%}
{% endmacro %}


{% macro kinetica__drop_schema(relation) -%}
  {%- call statement('drop_schema') -%}
    drop schema if exists {{ relation.without_identifier().render() }} cascade
  {%- endcall -%}
{% endmacro %}
