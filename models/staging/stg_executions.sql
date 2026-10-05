select
    execution_id,
    cast(executed_at as timestamp) as executed_at,
    cast(date_trunc('month', cast(executed_at as timestamp)) as date) as trade_month,
    member_id,
    symbol,
    product,
    liquidity_flag,
    cast(quantity as bigint) as quantity
from {{ ref('raw_executions') }}
