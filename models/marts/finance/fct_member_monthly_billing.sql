select
    member_id || '|' || cast(trade_month as varchar) as billing_key,
    member_id,
    trade_month,
    cast(sum(gross_fee) as decimal(18, 2)) as gross_fees,
    cast(sum(rebate) as decimal(18, 2)) as rebates,
    cast(sum(net_fee) as decimal(18, 2)) as net_billed
from {{ ref('fct_execution_fees') }}
group by member_id, trade_month
