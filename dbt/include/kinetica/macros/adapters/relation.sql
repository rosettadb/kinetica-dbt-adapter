{% macro kinetica__truncate_relation(relation) -%}
  {% call statement('truncate_relation') -%}
    truncate table {{ relation.render() }}
  {%- endcall %}
{% endmacro %}


{% macro kinetica__rename_relation(from_relation, to_relation) -%}
  {% call statement('rename_relation') -%}
    {{ get_rename_sql(from_relation, to_relation.identifier) }}
  {%- endcall %}
{% endmacro %}


{% macro kinetica__get_rename_table_sql(relation, new_name) -%}
    alter table {{ relation.render() }} rename to {{ adapter.quote_as_configured(new_name, 'identifier') }}
{%- endmacro %}


{% macro kinetica__get_rename_view_sql(relation, new_name) -%}
    {{ exceptions.raise_compiler_error(
        "Kinetica cannot rename views (" ~ relation.render() ~ "); dbt-kinetica replaces views with CREATE OR REPLACE VIEW instead."
    ) }}
{%- endmacro %}


{% macro kinetica__get_rename_materialized_view_sql(relation, new_name) -%}
    {{ exceptions.raise_compiler_error(
        "Kinetica cannot rename materialized views (" ~ relation.render() ~ ")."
    ) }}
{%- endmacro %}


{% macro kinetica__get_drop_sql(relation) -%}
    {%- if relation.is_view -%}
        {{ drop_view(relation) }}
    {%- elif relation.is_table -%}
        {{ drop_table(relation) }}
    {%- elif relation.is_materialized_view -%}
        {{ drop_materialized_view(relation) }}
    {%- else -%}
        drop table if exists {{ relation.render() }}
    {%- endif -%}
{%- endmacro %}


{% macro kinetica__drop_table(relation) -%}
    drop table if exists {{ relation.render() }}
{%- endmacro %}


{% macro kinetica__drop_view(relation) -%}
    drop view if exists {{ relation.render() }}
{%- endmacro %}


{% macro kinetica__drop_materialized_view(relation) -%}
    drop materialized view if exists {{ relation.render() }}
{%- endmacro %}


{#
  Kinetica has no COMMENT ON support that we can rely on across versions, so
  persist_docs is a documented no-op.
#}
{% macro kinetica__persist_docs(relation, model, for_relation, for_columns) -%}
  {% if (for_relation and config.persist_relation_docs() and model.description)
        or (for_columns and config.persist_column_docs() and model.columns) %}
    {{ log("dbt-kinetica: persist_docs is not supported on Kinetica; skipping for " ~ relation.render()) }}
  {% endif %}
{%- endmacro %}


{% macro kinetica__alter_relation_comment(relation, relation_comment) -%}
{%- endmacro %}


{% macro kinetica__alter_column_comment(relation, column_dict) -%}
{%- endmacro %}
