select
    product,
    liquidity_flag,
    cast(tier as integer) as tier,
    cast(rate_per_unit as decimal(10, 4)) as rate_per_unit,
    effective_from,
    effective_to
from {{ ref('raw_fee_schedule') }}
