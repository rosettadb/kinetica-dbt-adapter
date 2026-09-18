{# ---------- strings ---------------------------------------------------- #}

{#- Kinetica's CONCAT takes exactly two arguments; nest for more. -#}
{% macro kinetica__concat(fields) -%}
    {%- if fields | length == 0 -%}
        ''
    {%- elif fields | length == 1 -%}
        {{ fields[0] }}
    {%- else -%}
        concat({{ fields[0] }}, {{ kinetica__concat(fields[1:]) }})
    {%- endif -%}
{%- endmacro %}


{% macro kinetica__hash(field) -%}
    md5(cast({{ field }} as varchar))
{%- endmacro %}


{% macro kinetica__split_part(string_text, delimiter_text, part_number) -%}
    split({{ string_text }}, {{ delimiter_text }}, {{ part_number }})
{%- endmacro %}


{% macro kinetica__cast_bool_to_text(field) -%}
    case
        when {{ field }} is null then null
        when {{ field }} then 'true'
        else 'false'
    end
{%- endmacro %}


{% macro kinetica__escape_single_quotes(expression) -%}
{{ expression | replace("'", "''") }}
{%- endmacro %}


{# ---------- aggregates ------------------------------------------------- #}

{% macro kinetica__bool_or(expression) -%}
    (max(case when {{ expression }} then 1 else 0 end) = 1)
{%- endmacro %}


{% macro kinetica__any_value(expression) -%}
    min({{ expression }})
{%- endmacro %}


{% macro kinetica__listagg(measure, delimiter_text, order_by_clause, limit_num) -%}
    {%- if limit_num -%}
        {{ exceptions.warn("dbt-kinetica: listagg() ignores limit_num on Kinetica") }}
    {%- endif -%}
    string_agg({{ measure }}, {{ delimiter_text }}
        {%- if order_by_clause %} {{ order_by_clause }}{% endif -%}
    )
{%- endmacro %}


{# ---------- dates ------------------------------------------------------ #}

{% macro kinetica__dateadd(datepart, interval, from_date_or_timestamp) -%}
    timestampadd({{ datepart | upper }}, {{ interval }}, {{ from_date_or_timestamp }})
{%- endmacro %}


{% macro kinetica__datediff(first_date, second_date, datepart) -%}
    timestampdiff({{ datepart | upper }}, {{ first_date }}, {{ second_date }})
{%- endmacro %}


{% macro kinetica__date_trunc(datepart, date) -%}
    date_trunc({{ datepart | upper }}, {{ date }})
{%- endmacro %}


{% macro kinetica__last_day(date, datepart) -%}
    {%- if datepart | lower == 'month' -%}
        last_day({{ date }})
    {%- else -%}
        {{ dbt.default_last_day(date, datepart) }}
    {%- endif -%}
{%- endmacro %}


{# ---------- misc ------------------------------------------------------- #}

{% macro kinetica__array_construct(inputs, data_type) -%}
    {%- if inputs | length > 0 -%}
        array[ {{ inputs | join(' , ') }} ]
    {%- else -%}
        cast(null as {{ data_type }}[])
    {%- endif -%}
{%- endmacro %}
