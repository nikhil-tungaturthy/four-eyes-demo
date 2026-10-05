select
    cast(trade_month as varchar) || '|' || product as revenue_key,
    trade_month,
    product,
    cast(sum(gross_fee) as decimal(18, 2)) as gross_fees,
    cast(sum(rebate) as decimal(18, 2)) as rebates,
    cast(sum(net_fee) as decimal(18, 2)) as net_revenue
from {{ ref('fct_execution_fees') }}
group by trade_month, product
