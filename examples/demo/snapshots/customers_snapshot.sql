{% snapshot customers_snapshot %}

{{
    config(
        unique_key='customer_id',
        strategy='check',
        check_cols=['first_name', 'last_name', 'is_active']
    )
}}

select * from {{ ref('stg_customers') }}

{% endsnapshot %}
