with source as (
    select * from {{ source('lossguard', 'scored_transactions') }}
)

select
    transaction_id,
    event_time,
    processed_at,
    event_time::date as transaction_date,
    merchant_category,
    channel,
    amount::double precision as amount,
    order_margin_pct::double precision as order_margin_pct,
    customer_ltv_band,
    fraud_label,
    fraud_probability::double precision as fraud_probability,
    decision,
    verify_threshold::double precision as verify_threshold,
    decline_threshold::double precision as decline_threshold,
    realized_policy_cost::double precision as realized_policy_cost,
    baseline_cost::double precision as baseline_cost,
    estimated_savings::double precision as estimated_savings,
    model_version,
    explanation,
    feature_snapshot,
    case when fraud_label and decision in ('verify', 'decline') then 1 else 0 end as fraud_intervened,
    case when not fraud_label and decision = 'decline' then 1 else 0 end as false_decline,
    case when not fraud_label and decision = 'verify' then 1 else 0 end as legitimate_verified,
    case
        when fraud_label and decision = 'decline' then amount::double precision
        when fraud_label and decision = 'verify' then amount::double precision * 0.85
        else 0
    end as fraud_caught_value,
    case
        when fraud_label and decision = 'approve' then amount::double precision
        when fraud_label and decision = 'verify' then amount::double precision * 0.15
        else 0
    end as fraud_missed_cost,
    case
        when decision = 'verify' then
            3.0 + case when not fraud_label then
                (
                    amount::double precision * order_margin_pct::double precision
                    + case customer_ltv_band
                        when 'low' then 15.0
                        when 'medium' then 45.0
                        when 'high' then 120.0
                    end
                ) * 0.08
            else 0 end
        when not fraud_label and decision = 'decline' then
            amount::double precision * order_margin_pct::double precision
            + case customer_ltv_band
                when 'low' then 15.0
                when 'medium' then 45.0
                when 'high' then 120.0
            end
        else 0
    end as friction_cost,
    case
        when not fraud_label and decision = 'approve' then amount::double precision
        else 0
    end as normal_approval_value
from source
