-- Subledger-to-ledger tie-out: member billing must equal reported revenue each month.
with billed as (
    select trade_month, sum(net_billed) as billed
    from {{ ref('fct_member_monthly_billing') }}
    group by trade_month
),

reported as (
    select trade_month, sum(net_revenue) as revenue
    from {{ ref('fct_net_transaction_revenue') }}
    group by trade_month
)

select coalesce(b.trade_month, r.trade_month) as trade_month, b.billed, r.revenue
from billed as b
full outer join reported as r on b.trade_month = r.trade_month
where abs(coalesce(b.billed, 0) - coalesce(r.revenue, 0)) > 0.01
