{#
  CREATE [OR REPLACE] MATERIALIZED VIEW <schema>.<name>
      [REFRESH (ON CHANGE | ON QUERY | EVERY <n> (SECOND|MINUTE|HOUR|DAY) | MANUAL)]
  AS ( <select> )

  Model config `refresh` is passed through verbatim, e.g. refresh: "EVERY 5 MINUTES".
#}
{% macro kinetica__mv_refresh_clause() -%}
  {%- set refresh = config.get('refresh', none) -%}
  {%- if refresh %} refresh {{ refresh }}{% endif -%}
{%- endmacro %}


{% macro kinetica__get_create_materialized_view_as_sql(relation, sql) -%}
    create materialized view {{ relation.render() }}{{ kinetica__mv_refresh_clause() }}
    as (
      {{ sql }}
    )
{%- endmacro %}


{% macro kinetica__get_replace_materialized_view_sql(relation, sql) -%}
    create or replace materialized view {{ relation.render() }}{{ kinetica__mv_refresh_clause() }}
    as (
      {{ sql }}
    )
{%- endmacro %}


{% macro kinetica__refresh_materialized_view(relation) -%}
    refresh materialized view {{ relation.render() }}
{%- endmacro %}


{% macro kinetica__get_materialized_view_configuration_changes(existing_relation, new_config) -%}
    {# Kinetica exposes no cheap way to introspect refresh settings; treat as unchanged. #}
    {{ return(none) }}
{%- endmacro %}


{% macro kinetica__get_alter_materialized_view_as_sql(
    relation, configuration_changes, sql, existing_relation, backup_relation, intermediate_relation
) -%}
    {{ get_replace_sql(existing_relation, relation, sql) }}
{%- endmacro %}
