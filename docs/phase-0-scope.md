# Phase 0 — Scope and decision framing

## Problem statement

Fraud controls create two competing losses. Permissive controls approve fraudulent purchases;
aggressive controls reject legitimate customers and destroy margin, trust, and future value. A
classification score alone does not answer the operating question: **which action has the lowest
expected dollar cost for this transaction and merchant segment?**

LossGuard replays labelled Sparkov transactions event-by-event, scores each event, and recommends
`approve`, `verify`, or `decline`. Category thresholds are learned against a documented cost model.
The resulting action, expected and retrospective simulated costs, model version, and feature-level
explanation are stored for analysis. The dashboard translates them into fraud caught, fraud missed,
legitimate-customer friction, normal approvals, and threshold sensitivity.

“Real-time” here means source-order historical replay through a streaming architecture. LossGuard does
not currently receive live card-network or payment-provider traffic, authorize a payment, or wait
for delayed production dispute labels.

## Audience and decisions

| Audience | Decision supported |
|---|---|
| Fraud operations | Which transactions should be approved, verified, or declined? |
| Commercial leadership | Is simulated fraud reduction worth the modeled customer friction? |
| Data/ML engineering | Is ingestion valid, replayable, observable, and explainable? |
| Portfolio reviewer | Does the system connect infrastructure, modeling, reliability, and value? |

## Implemented scope

- Privacy-safe Sparkov replay through Redpanda and PostgreSQL.
- Dataset checksum/schema validation, event validation, and sanitized dead letters.
- Calibrated, cost-sensitive XGBoost scoring with per-category thresholds and SHAP.
- Authenticated FastAPI scoring and administrative model reload.
- dbt marts, Streamlit business dashboard, and plain-English explanation adapters.
- Optional Prometheus/Grafana/cAdvisor observability and Slack alerts.
- Scheduled Evidently drift reports with persisted error, freshness, and retention states.
- Pooled/batched database persistence, versioned migrations, and a transactional Kafka outbox.

## Success and reliability criteria

1. Dataset integrity and schema checks pass before training or replay begins.
2. Valid events consumed from Kafka commit their decision, metric, and outbox record in one database
   transaction; malformed Kafka events commit only a sanitized dead-letter summary and outbox record.
3. Source offsets advance only after that database transaction commits.
4. Kafka delivery is broker-confirmed. Delivery is at-least-once: a crash after acknowledgement but
   before the outbox status update can republish an event, so downstream consumers must use the
   stable transaction/outbox key for idempotency.
5. No direct card number, customer name, street address, or raw malformed payload enters Kafka,
   PostgreSQL, or application logs.
6. Drift failures are visible as database health states; reports beyond the configured maximum age
   are shown as stale rather than silently treated as healthy.
7. Dollar values remain documented simulations, not realized merchant revenue.

## Interview pitch

> I built a streaming fraud-decision simulator that optimizes a documented dollar-cost function,
> not accuracy alone. It validates and replays privacy-safe historical events, serves calibrated
> XGBoost decisions with SHAP evidence, persists them through a transactional outbox, and shows the
> fraud-versus-customer-friction trade-off with observability, drift health, and retention controls.

## Explicit non-goals

- Live payment authorization, production payment-provider ingestion, or automated customer action.
- Exactly-once delivery across PostgreSQL and Kafka; the implemented contract is durable,
  idempotency-friendly at-least-once delivery.
- Claims that retrospective simulated savings are realized revenue.
- Multi-region broker/database availability, production IAM/TLS, or an audited model registry.
- Delayed fraud-label reconciliation and independent production model validation.
- Producer-side invalid source rows are logged and skipped before Kafka; routing them to a source
  rejection store is not yet implemented.
