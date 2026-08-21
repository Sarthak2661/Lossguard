select
    merchant_category,
    sum(transaction_count) as transaction_count,
    sum(fraud_transaction_count) as fraud_transaction_count,
    sum(fraud_intervened_count) as fraud_intervened_count,
    sum(false_decline_count) as false_decline_count,
    sum(legitimate_verified_count) as legitimate_verified_count,
    sum(approved_count) as approved_count,
    sum(verified_count) as verified_count,
    sum(declined_count) as declined_count,
    sum(gross_fraud_exposure) as gross_fraud_exposure,
    sum(policy_cost) as policy_cost,
    sum(baseline_cost) as baseline_cost,
    sum(estimated_savings) as estimated_savings,
    sum(fraud_caught_value) as fraud_caught_value,
    sum(fraud_missed_cost) as fraud_missed_cost,
    sum(friction_cost) as friction_cost,
    sum(normal_approval_value) as normal_approval_value,
    sum(fraud_intervened_count)::double precision
      / nullif(sum(fraud_transaction_count), 0) as fraud_intervention_rate,
    sum(false_decline_count)::double precision
      / nullif(sum(transaction_count - fraud_transaction_count), 0) as false_decline_rate,
    max(source_freshness) as source_freshness
from {{ ref('mart_daily_segment_kpis') }}
group by 1
