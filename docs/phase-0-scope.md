# Phase 0 — Scope and decision framing

## Problem statement

Fraud controls create two competing losses. Permissive controls approve fraudulent purchases and
create chargeback losses; aggressive controls reject legitimate customers and destroy margin,
trust, and future value. A conventional fraud model reports classification quality but does not
answer the operating question: **which action has the lowest expected dollar cost for this
transaction and merchant segment?**

LossGuard replays labelled Sparkov transactions as a live stream, scores each event, and recommends
`approve`, `verify`, or `decline`. Category-specific thresholds are learned against a documented
cost function. The resulting decision, expected cost, realized simulation cost, and feature-level
explanation are stored for analysis. The dashboard translates model outputs into business outcomes:
fraud captured, legitimate customers affected, estimated loss avoided, and the sensitivity of those
outcomes to threshold changes.

## Audience and decisions

| Audience | Decision supported |
|---|---|
| Fraud operations | Which transactions need verification or decline? |
| Commercial leadership | Is prevented fraud worth the customer friction introduced? |
| Data/ML engineering | Is the stream valid, reproducible, and explainable? |
| Portfolio reviewer | Can the builder connect infrastructure, modeling, and business value? |

## Phase 0–3 scope

- Local, Dockerized Redpanda and PostgreSQL platform.
- Privacy-safe replay of the supplied Sparkov train/test CSV files.
- Schema validation and dead-letter handling.
- Cost-sensitive XGBoost scoring with per-category action thresholds.
- FastAPI model service with SHAP explanations.
- dbt models for consistent business KPIs.
- Streamlit decision dashboard and threshold simulator.

## Success criteria

1. Valid source rows become scored database records; invalid events remain inspectable.
2. No direct card number, customer name, or street address enters Kafka, logs, or PostgreSQL.
3. The scoring endpoint returns probabilities, one of three actions, cost estimates, and reasons.
4. dbt marts reconcile transaction and decision counts to the scored source table.
5. The dashboard states its source, freshness, simulation assumptions, and metric definitions.

## Interview pitch

> I built a real-time fraud decision system that optimizes dollars, not accuracy alone. It streams
> interpretable transaction data, protects customer identifiers, validates and scores each event,
> and selects approve, verification, or decline thresholds separately for merchant categories. A
> business dashboard then shows the trade-off between fraud avoided and legitimate-customer
> friction, with transaction-level SHAP explanations so each recommendation is auditable.

## Explicit non-goals through Phase 3

- Production card-processing integration, payment authorization, or automated customer action.
- Claims that simulated cost savings are realized merchant revenue.
- Phase 4 observability/Slack alerts, Phase 5 drift automation, or public deployment.
