from __future__ import annotations

import json
import logging
import time

import psycopg

from lossguard.schemas import RejectedEvent, ScoreResponse, TransactionEvent

LOGGER = logging.getLogger(__name__)


class TransactionRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def wait_until_ready(self, attempts: int = 30) -> None:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                with psycopg.connect(self.database_url) as connection:
                    connection.execute("SELECT 1")
                return
            except psycopg.Error as exc:
                last_error = exc
                LOGGER.warning("Postgres not ready (attempt %s/%s)", attempt + 1, attempts)
                time.sleep(min(1 + attempt * 0.2, 5))
        raise RuntimeError("Postgres did not become ready") from last_error

    def save_score(self, event: TransactionEvent, score: ScoreResponse) -> None:
        query = """
            INSERT INTO scored_transactions (
                transaction_id, event_time, customer_id, merchant, merchant_category,
                channel, amount, order_margin_pct, customer_ltv_band, fraud_label,
                fraud_probability, decision, verify_threshold, decline_threshold,
                expected_cost_approve, expected_cost_verify, expected_cost_decline,
                realized_policy_cost, baseline_cost, estimated_savings, model_version,
                explanation, feature_snapshot
            ) VALUES (
                %(transaction_id)s, %(event_time)s, %(customer_id)s, %(merchant)s,
                %(merchant_category)s, %(channel)s, %(amount)s, %(order_margin_pct)s,
                %(customer_ltv_band)s, %(fraud_label)s, %(fraud_probability)s,
                %(decision)s, %(verify_threshold)s, %(decline_threshold)s,
                %(expected_cost_approve)s, %(expected_cost_verify)s,
                %(expected_cost_decline)s, %(realized_policy_cost)s, %(baseline_cost)s,
                %(estimated_savings)s, %(model_version)s, %(explanation)s::jsonb,
                %(feature_snapshot)s::jsonb
            )
            ON CONFLICT (transaction_id) DO UPDATE SET
                processed_at = NOW(), fraud_probability = EXCLUDED.fraud_probability,
                decision = EXCLUDED.decision, verify_threshold = EXCLUDED.verify_threshold,
                decline_threshold = EXCLUDED.decline_threshold,
                expected_cost_approve = EXCLUDED.expected_cost_approve,
                expected_cost_verify = EXCLUDED.expected_cost_verify,
                expected_cost_decline = EXCLUDED.expected_cost_decline,
                realized_policy_cost = EXCLUDED.realized_policy_cost,
                baseline_cost = EXCLUDED.baseline_cost,
                estimated_savings = EXCLUDED.estimated_savings,
                explanation_text = CASE
                    WHEN scored_transactions.model_version IS DISTINCT FROM EXCLUDED.model_version
                    THEN NULL ELSE scored_transactions.explanation_text END,
                explanation_source = CASE
                    WHEN scored_transactions.model_version IS DISTINCT FROM EXCLUDED.model_version
                    THEN NULL ELSE scored_transactions.explanation_source END,
                explanation_model = CASE
                    WHEN scored_transactions.model_version IS DISTINCT FROM EXCLUDED.model_version
                    THEN NULL ELSE scored_transactions.explanation_model END,
                explanation_generated_at = CASE
                    WHEN scored_transactions.model_version IS DISTINCT FROM EXCLUDED.model_version
                    THEN NULL ELSE scored_transactions.explanation_generated_at END,
                model_version = EXCLUDED.model_version,
                explanation = EXCLUDED.explanation,
                feature_snapshot = EXCLUDED.feature_snapshot
        """
        values = {
            **event.model_dump(mode="json"),
            **score.model_dump(mode="json", exclude={"transaction_id"}),
            "explanation": json.dumps([item.model_dump() for item in score.explanation]),
            "feature_snapshot": json.dumps(score.feature_snapshot),
        }
        with psycopg.connect(self.database_url) as connection:
            connection.execute(query, values)

    def save_rejection(self, rejection: RejectedEvent) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO rejected_transactions
                    (source_topic, error_type, error_message, transaction_id, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (
                    rejection.source_topic,
                    rejection.error_type,
                    rejection.error_message,
                    rejection.transaction_id,
                    json.dumps(rejection.payload, default=str),
                ),
            )

    def record_metric(self, name: str, value: float, labels: dict | None = None) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO pipeline_metrics (metric_name, metric_value, labels)
                VALUES (%s, %s, %s::jsonb)
                """,
                (name, value, json.dumps(labels or {})),
            )
