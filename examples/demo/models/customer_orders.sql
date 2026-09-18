{{ config(materialized='table', ttl=1440) }}

select
    c.customer_id,
    c.first_name,
    c.last_name,
    count(o.order_id) as order_count,
    sum(o.amount) as lifetime_value,
    max(o.order_date) as last_order_date
from {{ ref('stg_customers') }} c
left join {{ ref('stg_orders') }} o
    on o.customer_id = c.customer_id
group by c.customer_id, c.first_name, c.last_name
