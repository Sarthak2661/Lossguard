select
    transaction_date as metric_date,
    merchant_category,
    count(*) as transaction_count,
    sum(fraud_label::int) as fraud_transaction_count,
    sum(fraud_intervened) as fraud_intervened_count,
    sum(false_decline) as false_decline_count,
    sum(legitimate_verified) as legitimate_verified_count,
    sum((decision = 'approve')::int) as approved_count,
    sum((decision = 'verify')::int) as verified_count,
    sum((decision = 'decline')::int) as declined_count,
    sum(case when fraud_label then amount else 0 end) as gross_fraud_exposure,
    sum(coalesce(realized_policy_cost, 0)) as policy_cost,
    sum(coalesce(baseline_cost, 0)) as baseline_cost,
    sum(coalesce(estimated_savings, 0)) as estimated_savings,
    sum(fraud_caught_value) as fraud_caught_value,
    sum(fraud_missed_cost) as fraud_missed_cost,
    sum(friction_cost) as friction_cost,
    sum(normal_approval_value) as normal_approval_value,
    avg(fraud_probability) as average_fraud_probability,
    max(processed_at) as source_freshness
from {{ ref('stg_scored_transactions') }}
group by 1, 2
