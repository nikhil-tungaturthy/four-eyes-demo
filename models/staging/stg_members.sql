select
    member_id,
    member_name,
    member_type,
    cast(onboarded_on as date) as onboarded_on
from {{ ref('raw_members') }}
