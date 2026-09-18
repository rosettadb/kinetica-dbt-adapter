{% materialization incremental, adapter='kinetica' -%}

  {%- set existing_relation = load_cached_relation(this) -%}
  {%- set target_relation = this.incorporate(type='table') -%}
  {%- set temp_relation = make_temp_relation(target_relation) -%}

  {%- set unique_key = config.get('unique_key') -%}
  {%- set existing_is_table = existing_relation is not none and existing_relation.is_table -%}
  {%- set full_refresh_mode = (should_full_refresh() or (existing_relation is not none and not existing_is_table)) -%}
  {%- set on_schema_change = incremental_validate_on_schema_change(config.get('on_schema_change'), default='ignore') -%}
  {%- set grant_config = config.get('grants') -%}

  {#-- a leftover temp table from a failed run must go before we start --#}
  {%- set preexisting_temp_relation = load_cached_relation(temp_relation) -%}
  {{ drop_relation_if_exists(preexisting_temp_relation) }}

  {{ run_hooks(pre_hooks, inside_transaction=False) }}
  {{ run_hooks(pre_hooks, inside_transaction=True) }}

  {% set to_drop = [] %}
  {% set incremental_strategy = config.get('incremental_strategy') or 'default' %}
  {% set strategy_sql_macro_func = adapter.get_incremental_strategy_macro(context, incremental_strategy) %}

  {% if existing_relation is none %}
      {% set build_sql = get_create_table_as_sql(False, target_relation, sql) %}
  {% elif full_refresh_mode %}
      {% if not existing_is_table %}
        {{ log("Dropping relation " ~ existing_relation.render() ~ " because it is of type " ~ existing_relation.type) }}
        {% do adapter.drop_relation(existing_relation) %}
      {% endif %}
      {% set build_sql = get_create_table_as_sql(False, target_relation, sql) %}
  {% else %}
    {% do run_query(get_create_table_as_sql(True, temp_relation, sql)) %}
    {% do to_drop.append(temp_relation) %}

    {% set contract_config = config.get('contract') %}
    {% if not contract_config or not contract_config.enforced %}
      {% do adapter.expand_target_column_types(
               from_relation=temp_relation,
               to_relation=target_relation) %}
    {% endif %}

    {% set dest_columns = process_schema_changes(on_schema_change, temp_relation, existing_relation) %}
    {% if not dest_columns %}
      {% set dest_columns = adapter.get_columns_in_relation(existing_relation) %}
    {% endif %}

    {% set incremental_predicates = config.get('predicates', none) or config.get('incremental_predicates', none) %}
    {% set strategy_arg_dict = ({
        'target_relation': target_relation,
        'temp_relation': temp_relation,
        'unique_key': unique_key,
        'dest_columns': dest_columns,
        'incremental_predicates': incremental_predicates
    }) %}
    {% set build_sql = strategy_sql_macro_func(strategy_arg_dict) %}
  {% endif %}

  {% call statement("main") %}
      {{ build_sql }}
  {% endcall %}

  {% if existing_relation is none or full_refresh_mode %}
    {% do create_indexes(target_relation) %}
  {% endif %}

  {% set should_revoke = should_revoke(existing_relation, full_refresh_mode) %}
  {% do apply_grants(target_relation, grant_config, should_revoke=should_revoke) %}

  {% do persist_docs(target_relation, model) %}

  {{ run_hooks(post_hooks, inside_transaction=True) }}

  {% do adapter.commit() %}

  {% for rel in to_drop %}
      {% do adapter.drop_relation(rel) %}
  {% endfor %}

  {{ run_hooks(post_hooks, inside_transaction=False) }}

  {{ return({'relations': [target_relation]}) }}

{%- endmaterialization %}
