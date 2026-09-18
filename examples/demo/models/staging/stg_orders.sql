select
    id as order_id,
    customer_id,
    order_date,
    amount,
    status
from {{ ref('raw_orders') }}
