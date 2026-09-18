{% macro kinetica__current_timestamp() -%}
  now()
{%- endmacro %}


{% macro kinetica__snapshot_get_time() -%}
  now()
{%- endmacro %}


{% macro kinetica__snapshot_string_as_time(timestamp) -%}
    {%- set result = "cast('" ~ timestamp ~ "' as datetime)" -%}
    {{ return(result) }}
{%- endmacro %}


{% macro kinetica__current_timestamp_backcompat() -%}
    now()
{%- endmacro %}


{% macro kinetica__current_timestamp_in_utc_backcompat() -%}
    now()
{%- endmacro %}
