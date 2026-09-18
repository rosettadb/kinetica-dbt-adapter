{#
  Kinetica has no MERGE; the snapshot merge is an UPDATE ... FROM followed by
  an INSERT ... SELECT.  The cursor splits the two statements on ';'.

  Verified on Kinetica 7.2.3: the update target may not be aliased, it must be
  repeated in the FROM clause, and its columns are referenced by bare table name.
#}
{% macro kinetica__snapshot_merge_sql(target, source, insert_cols) -%}
    {%- set insert_cols_csv = insert_cols | join(', ') -%}
    {%- set columns = config.get("snapshot_table_column_names") or get_snapshot_table_column_names() -%}
    {%- set dest = adapter.quote(target.identifier) -%}

    update {{ target.render() }}
    set {{ columns.dbt_valid_to }} = DBT_INTERNAL_SOURCE.{{ columns.dbt_valid_to }}
    from {{ target.render() }}, {{ source }} as DBT_INTERNAL_SOURCE
    where DBT_INTERNAL_SOURCE.{{ columns.dbt_scd_id }} = {{ dest }}.{{ columns.dbt_scd_id }}
      and DBT_INTERNAL_SOURCE.dbt_change_type in ('update', 'delete')
    {%- if config.get("dbt_valid_to_current") %}
      and ({{ dest }}.{{ columns.dbt_valid_to }} = {{ config.get('dbt_valid_to_current') }}
           or {{ dest }}.{{ columns.dbt_valid_to }} is null)
    {%- else %}
      and {{ dest }}.{{ columns.dbt_valid_to }} is null
    {%- endif %};

    insert into {{ target.render() }} ({{ insert_cols_csv }})
    select {{ insert_cols_csv }}
    from {{ source }}
    where dbt_change_type = 'insert'
{%- endmacro %}


{#- Kinetica has no MD5(); SHA256() returns a 64-char hex string. -#}
{% macro kinetica__snapshot_hash_arguments(args) -%}
    {%- set parts = [] -%}
    {%- for arg in args -%}
        {%- do parts.append("coalesce(cast(" ~ arg ~ " as varchar), '')") -%}
        {%- if not loop.last -%}{%- do parts.append("'|'") -%}{%- endif -%}
    {%- endfor -%}
    sha256({{ kinetica__concat(parts) }})
{%- endmacro %}


{% macro kinetica__post_snapshot(staging_relation) -%}
    {# the staging relation is a real (temp) table; clean it up #}
    {% do adapter.drop_relation(staging_relation) %}
{%- endmacro %}


{% macro kinetica__get_true_sql() -%}
    {{ return('1 = 1') }}
{%- endmacro %}
