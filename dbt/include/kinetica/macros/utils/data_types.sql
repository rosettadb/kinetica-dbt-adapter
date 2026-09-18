{% macro kinetica__type_string() -%}
    {{ return("varchar") }}
{%- endmacro %}

{% macro kinetica__type_timestamp() -%}
    {{ return("timestamp") }}
{%- endmacro %}

{% macro kinetica__type_float() -%}
    {{ return("double") }}
{%- endmacro %}

{% macro kinetica__type_numeric() -%}
    {{ return("decimal(18,4)") }}
{%- endmacro %}

{% macro kinetica__type_bigint() -%}
    {{ return("bigint") }}
{%- endmacro %}

{% macro kinetica__type_int() -%}
    {{ return("integer") }}
{%- endmacro %}

{% macro kinetica__type_boolean() -%}
    {{ return("boolean") }}
{%- endmacro %}
