select
    member_id || '|' || cast(trade_month as varchar) as activity_key,
    member_id,
    trade_month,
    count(*) as executions,
    count(*) filter (where liquidity_flag = 'A') as adding_executions,
    count(distinct symbol) as distinct_symbols
from {{ ref('stg_executions') }}
group by member_id, trade_month
