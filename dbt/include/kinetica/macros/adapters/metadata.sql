{#
  Metadata is read through Kinetica's native /show/table and /show/schema
  endpoints (see KineticaAdapter in impl.py).  These macros exist so that user
  code calling the dispatched macro names still works.
#}
{% macro kinetica__list_schemas(database) -%}
  {{ return(adapter.list_schemas(database)) }}
{%- endmacro %}


{% macro kinetica__check_schema_exists(information_schema, schema) -%}
  {{ return(adapter.check_schema_exists(information_schema.database, schema)) }}
{%- endmacro %}


{% macro kinetica__list_relations_without_caching(schema_relation) -%}
  {{ return(adapter.list_relations_without_caching(schema_relation)) }}
{%- endmacro %}


{% macro kinetica__get_columns_in_relation(relation) -%}
  {{ return(adapter.get_columns_in_relation(relation)) }}
{%- endmacro %}


{% macro kinetica__information_schema_name(database) -%}
  ki_catalog
{%- endmacro %}


{% macro kinetica__get_relation_last_modified(information_schema, relations) -%}
  {{ exceptions.raise_not_implemented(
    'get_relation_last_modified is not supported by dbt-kinetica; use loaded_at_field for source freshness') }}
{%- endmacro %}
