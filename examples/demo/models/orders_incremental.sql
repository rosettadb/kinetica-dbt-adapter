{{
    config(
        materialized='incremental',
        incremental_strategy='delete+insert',
        unique_key='order_id'
    )
}}

select
    order_id,
    customer_id,
    order_date,
    amount,
    status
from {{ ref('stg_orders') }}

{% if is_incremental() %}
where order_date >= (select coalesce(max(order_date), cast('1900-01-01' as date)) from {{ this }})
{% endif %}
