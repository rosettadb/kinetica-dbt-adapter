{#
  Kinetica supports CREATE OR REPLACE TABLE ... AS, so a table build is a
  single atomic statement.  No intermediate/backup relations, no renames.
#}
{% materialization table, adapter='kinetica' %}

  {%- set existing_relation = load_cached_relation(this) -%}
  {%- set target_relation = this.incorporate(type='table') -%}
  {%- set grant_config = config.get('grants') -%}

  {{ run_hooks(pre_hooks, inside_transaction=False) }}
  {{ run_hooks(pre_hooks, inside_transaction=True) }}

  {%- if existing_relation is not none and not existing_relation.is_table -%}
    {{ log("Dropping relation " ~ existing_relation.render() ~ " because it is of type " ~ existing_relation.type) }}
    {{ drop_relation_if_exists(existing_relation) }}
  {%- endif -%}

  {% call statement('main') -%}
    {{ get_create_table_as_sql(False, target_relation, sql) }}
  {%- endcall %}

  {% do create_indexes(target_relation) %}

  {{ run_hooks(post_hooks, inside_transaction=True) }}

  {% set should_revoke = should_revoke(existing_relation, full_refresh_mode=True) %}
  {% do apply_grants(target_relation, grant_config, should_revoke=should_revoke) %}

  {% do persist_docs(target_relation, model) %}

  {{ adapter.commit() }}

  {{ run_hooks(post_hooks, inside_transaction=False) }}

  {{ return({'relations': [target_relation]}) }}

{% endmaterialization %}
