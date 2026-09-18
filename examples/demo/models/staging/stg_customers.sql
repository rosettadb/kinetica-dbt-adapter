select
    id as customer_id,
    first_name,
    last_name,
    signed_up_at,
    is_active
from {{ ref('raw_customers') }}
