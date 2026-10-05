select
    e.execution_id,
    e.executed_at,
    e.trade_month,
    e.member_id,
    e.product,
    e.liquidity_flag,
    e.quantity,
    coalesce(v.rebate_tier, 3) as rebate_tier,
    f.rate_per_unit,
    e.quantity * f.rate_per_unit as fee_amount  -- positive is a fee, negative is a rebate
from {{ ref('stg_executions') }} as e
left join {{ ref('int_member_monthly_volume') }} as v
    on e.member_id = v.member_id and e.trade_month = v.trade_month
join {{ ref('stg_fee_schedule') }} as f
    on f.product = e.product
    and f.liquidity_flag = e.liquidity_flag
    and f.tier = coalesce(v.rebate_tier, 3)
    and e.executed_at >= f.effective_from
    and (f.effective_to is null or e.executed_at < f.effective_to)
