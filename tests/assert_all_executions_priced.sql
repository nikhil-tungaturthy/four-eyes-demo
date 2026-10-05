-- Completeness control: every execution must produce exactly one fee row.
select e.execution_id
from {{ ref('stg_executions') }} as e
left join {{ ref('fct_execution_fees') }} as f on e.execution_id = f.execution_id
where f.execution_id is null
