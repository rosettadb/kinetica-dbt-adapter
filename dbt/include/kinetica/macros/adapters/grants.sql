{#
  Kinetica: GRANT <privilege> ON TABLE <schema>.<table> TO <user|role>
  One grantee per statement.  We never try to diff existing grants (Kinetica
  has no SHOW GRANTS equivalent that maps cleanly), so grants configured on a
  model are (re)applied idempotently and nothing is revoked automatically.
#}
{% macro kinetica__support_multiple_grantees_per_dcl_statement() -%}
    {{ return(False) }}
{%- endmacro %}


{% macro kinetica__copy_grants() -%}
    {{ return(True) }}
{%- endmacro %}


{% macro kinetica__get_grant_sql(relation, privilege, grantees) -%}
    grant {{ privilege }} on table {{ relation.render() }} to {{ grantees | join(', ') }}
{%- endmacro %}


{% macro kinetica__get_revoke_sql(relation, privilege, grantees) -%}
    revoke {{ privilege }} on table {{ relation.render() }} from {{ grantees | join(', ') }}
{%- endmacro %}


{% macro kinetica__call_dcl_statements(dcl_statement_list) %}
    {% for dcl_statement in dcl_statement_list %}
        {% call statement('grant_or_revoke') %}
            {{ dcl_statement }}
        {% endcall %}
    {% endfor %}
{% endmacro %}


{% macro kinetica__apply_grants(relation, grant_config, should_revoke=True) %}
    {% if grant_config %}
        {% set grant_statement_list = get_dcl_statement_list(relation, grant_config, get_grant_sql) %}
        {% if grant_statement_list %}
            {{ call_dcl_statements(grant_statement_list) }}
        {% endif %}
    {% endif %}
{% endmacro %}
