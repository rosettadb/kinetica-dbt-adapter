{#
  Kinetica auto-commits every statement, so there is no transaction to open or
  close around hooks.  The global implementation issues a literal `commit;`
  before the first out-of-transaction hook; we redefine the macro (it is not
  dispatched) to skip that.
#}
{% macro run_hooks(hooks, inside_transaction=True) %}
  {% for hook in hooks | selectattr('transaction', 'equalto', inside_transaction) %}
    {% set rendered = render(hook.get('sql')) | trim %}
    {% if (rendered | length) > 0 %}
      {% call statement(auto_begin=inside_transaction) %}
        {{ rendered }}
      {% endcall %}
    {% endif %}
  {% endfor %}
{% endmacro %}
