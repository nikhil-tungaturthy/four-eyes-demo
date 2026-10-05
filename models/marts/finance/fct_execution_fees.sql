select
    execution_id,
    executed_at,
    trade_month,
    member_id,
    product,
    liquidity_flag,
    quantity,
    rebate_tier,
    cast(case when fee_amount > 0 then fee_amount else 0 end as decimal(18, 2)) as gross_fee,
    cast(case when fee_amount < 0 then fee_amount else 0 end as decimal(18, 2)) as rebate,
    cast(fee_amount as decimal(18, 2)) as net_fee
from {{ ref('int_executions_priced') }}
