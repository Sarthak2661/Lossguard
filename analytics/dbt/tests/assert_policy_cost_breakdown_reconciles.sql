select
    metric_date,
    merchant_category,
    policy_cost,
    fraud_missed_cost + friction_cost as reconstructed_policy_cost
from {{ ref('mart_daily_segment_kpis') }}
where abs(policy_cost - (fraud_missed_cost + friction_cost)) > 0.02
