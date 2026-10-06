with monthly as (
    select member_id, trade_month, sum(quantity) as total_quantity
    from {{ ref('stg_executions') }}
    where product in ('equity', 'etf')
    group by member_id, trade_month
)

select
    member_id,
    trade_month,
    total_quantity,
    case
        when total_quantity > 5000000 then 1
        when total_quantity >= 1000000 then 2
        else 3
    end as rebate_tier
from monthly
