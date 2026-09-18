{% macro kinetica__get_incremental_default_sql(arg_dict) -%}
  {{ return(get_incremental_append_sql(arg_dict)) }}
{%- endmacro %}


{#
  Kinetica has no MERGE statement.  delete+insert is expressed as
      DELETE FROM target WHERE <key expr> IN (SELECT DISTINCT <key expr> FROM source);
      INSERT INTO target (...) SELECT ... FROM source
  Composite keys are compared through a concatenated string so that no table
  aliases or row-value constructors are required.
#}
{% macro kinetica__key_expression(unique_key) -%}
  {%- if unique_key is string -%}
    {%- set keys = [unique_key] -%}
  {%- else -%}
    {%- set keys = unique_key -%}
  {%- endif -%}
  {%- if keys | length == 1 -%}
    {{ keys[0] }}
  {%- else -%}
    {%- set parts = [] -%}
    {%- for key in keys -%}
      {%- do parts.append("coalesce(cast(" ~ key ~ " as varchar), '')") -%}
      {%- if not loop.last -%}{%- do parts.append("'||'") -%}{%- endif -%}
    {%- endfor -%}
    {{ kinetica__concat(parts) }}
  {%- endif -%}
{%- endmacro %}


{% macro kinetica__get_delete_insert_merge_sql(target, source, unique_key, dest_columns, incremental_predicates) -%}
    {%- set dest_cols_csv = get_quoted_csv(dest_columns | map(attribute="name")) -%}

    {% if unique_key %}
        {%- set key_expr = kinetica__key_expression(unique_key) -%}
        delete from {{ target }}
        where {{ key_expr }} in (
            select distinct {{ key_expr }}
            from {{ source }}
        )
        {%- if incremental_predicates %}
            {% for predicate in incremental_predicates %}
                and {{ predicate }}
            {% endfor %}
        {%- endif -%};
    {% endif %}

    insert into {{ target }} ({{ dest_cols_csv }})
    (
        select {{ dest_cols_csv }}
        from {{ source }}
    )
{%- endmacro %}


{% macro kinetica__get_incremental_merge_sql(arg_dict) -%}
  {{ exceptions.raise_compiler_error(
      "Kinetica has no MERGE statement. Use incremental_strategy='delete+insert' (or 'append') instead."
  ) }}
{%- endmacro %}


{% macro kinetica__get_incremental_insert_overwrite_sql(arg_dict) -%}
  {{ exceptions.raise_compiler_error(
      "The 'insert_overwrite' incremental strategy is not supported by dbt-kinetica."
  ) }}
{%- endmacro %}


{% macro kinetica__microbatch_timestamp_literal(value) -%}
  {%- if value is string -%}
    {%- set text = value -%}
  {%- elif value.strftime is defined -%}
    {%- set text = value.strftime('%Y-%m-%d %H:%M:%S') -%}
  {%- else -%}
    {%- set text = value | string -%}
  {%- endif -%}
  cast('{{ text }}' as datetime)
{%- endmacro %}


{#
  microbatch: replace the rows of the batch's event-time window.
#}
{% macro kinetica__get_incremental_microbatch_sql(arg_dict) -%}
  {%- set target = arg_dict["target_relation"] -%}
  {%- set source = arg_dict["temp_relation"] -%}
  {%- set dest_columns = arg_dict["dest_columns"] -%}
  {%- set incremental_predicates = arg_dict.get("incremental_predicates") -%}
  {%- set event_time = config.get('event_time') -%}
  {%- set batch_start = config.get("__dbt_internal_microbatch_event_time_start") -%}
  {%- set batch_end = config.get("__dbt_internal_microbatch_event_time_end") -%}

  {%- if not event_time -%}
    {{ exceptions.raise_compiler_error("The 'microbatch' strategy requires an 'event_time' config on the model.") }}
  {%- endif -%}

  {%- set dest_cols_csv = get_quoted_csv(dest_columns | map(attribute="name")) -%}

  delete from {{ target }}
  where 1 = 1
  {%- if batch_start %}
    and {{ event_time }} >= {{ kinetica__microbatch_timestamp_literal(batch_start) }}
  {%- endif %}
  {%- if batch_end %}
    and {{ event_time }} < {{ kinetica__microbatch_timestamp_literal(batch_end) }}
  {%- endif %}
  {%- if incremental_predicates %}
    {% for predicate in incremental_predicates %}
      and {{ predicate }}
    {% endfor %}
  {%- endif -%};

  insert into {{ target }} ({{ dest_cols_csv }})
  (
      select {{ dest_cols_csv }}
      from {{ source }}
  )
{%- endmacro %}
