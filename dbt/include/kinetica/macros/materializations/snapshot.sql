{#
  Kinetica has no MERGE; the snapshot merge is an UPDATE ... FROM followed by
  an INSERT ... SELECT.  The cursor splits the two statements on ';'.
#}
{% macro kinetica__snapshot_merge_sql(target, source, insert_cols) -%}
    {%- set insert_cols_csv = insert_cols | join(', ') -%}
    {%- set columns = config.get("snapshot_table_column_names") or get_snapshot_table_column_names() -%}

    update {{ target.render() }} as DBT_INTERNAL_DEST
    set {{ columns.dbt_valid_to }} = DBT_INTERNAL_SOURCE.{{ columns.dbt_valid_to }}
    from {{ source }} as DBT_INTERNAL_SOURCE
    where DBT_INTERNAL_SOURCE.{{ columns.dbt_scd_id }} = DBT_INTERNAL_DEST.{{ columns.dbt_scd_id }}
      and DBT_INTERNAL_SOURCE.dbt_change_type in ('update', 'delete')
    {%- if config.get("dbt_valid_to_current") %}
      and (DBT_INTERNAL_DEST.{{ columns.dbt_valid_to }} = {{ config.get('dbt_valid_to_current') }}
           or DBT_INTERNAL_DEST.{{ columns.dbt_valid_to }} is null)
    {%- else %}
      and DBT_INTERNAL_DEST.{{ columns.dbt_valid_to }} is null
    {%- endif %};

    insert into {{ target.render() }} ({{ insert_cols_csv }})
    select {{ insert_cols_csv }}
    from {{ source }}
    where dbt_change_type = 'insert'
{%- endmacro %}


{% macro kinetica__snapshot_hash_arguments(args) -%}
    {%- set parts = [] -%}
    {%- for arg in args -%}
        {%- do parts.append("coalesce(cast(" ~ arg ~ " as varchar), '')") -%}
        {%- if not loop.last -%}{%- do parts.append("'|'") -%}{%- endif -%}
    {%- endfor -%}
    md5({{ kinetica__concat(parts) }})
{%- endmacro %}


{% macro kinetica__post_snapshot(staging_relation) -%}
    {# the staging relation is a real (temp) table; clean it up #}
    {% do adapter.drop_relation(staging_relation) %}
{%- endmacro %}


{% macro kinetica__get_true_sql() -%}
    {{ return('1 = 1') }}
{%- endmacro %}
