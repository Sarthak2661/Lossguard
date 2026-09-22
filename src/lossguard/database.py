from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from lossguard.schemas import RejectedEvent, ScoreResponse, TransactionEvent

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutboxRecord:
    dedupe_key: str
    topic: str
    message_key: str
    payload: dict[str, Any]


@dataclass
class WriteBatch:
    scores: list[tuple[TransactionEvent, ScoreResponse]] = field(default_factory=list)
    rejections: list[RejectedEvent] = field(default_factory=list)
    metrics: list[tuple[str, float, dict[str, Any]]] = field(default_factory=list)
    outbox: list[OutboxRecord] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.scores) + len(self.rejections)


SCORE_UPSERT = """
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
        processed_at = NOW(), event_time = EXCLUDED.event_time,
        customer_id = EXCLUDED.customer_id, merchant = EXCLUDED.merchant,
        merchant_category = EXCLUDED.merchant_category, channel = EXCLUDED.channel,
        amount = EXCLUDED.amount, order_margin_pct = EXCLUDED.order_margin_pct,
        customer_ltv_band = EXCLUDED.customer_ltv_band,
        fraud_label = EXCLUDED.fraud_label,
        fraud_probability = EXCLUDED.fraud_probability,
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


class TransactionRepository:
    """Pooled PostgreSQL repository with atomic batch and outbox persistence."""

    def __init__(
        self,
        database_url: str,
        *,
        min_pool_size: int = 1,
        max_pool_size: int = 8,
        pool: ConnectionPool | None = None,
    ):
        self.database_url = database_url
        self.pool = pool or ConnectionPool(
            conninfo=database_url,
            min_size=min_pool_size,
            max_size=max_pool_size,
            open=False,
            kwargs={"connect_timeout": 5},
        )

    def _ensure_open(self, *, wait: bool = False) -> None:
        if self.pool.closed:
            self.pool.open(wait=wait, timeout=30)

    def wait_until_ready(self, attempts: int = 30) -> None:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                self._ensure_open(wait=True)
                with self.pool.connection() as connection:
                    connection.execute("SELECT 1")
                return
            except (psycopg.Error, PoolTimeout) as exc:
                last_error = exc
                LOGGER.warning("Postgres not ready (attempt %s/%s)", attempt + 1, attempts)
                time.sleep(min(1 + attempt * 0.2, 5))
        raise RuntimeError("Postgres did not become ready") from last_error

    def close(self) -> None:
        self.pool.close()

    @staticmethod
    def _score_values(event: TransactionEvent, score: ScoreResponse) -> dict[str, Any]:
        return {
            **event.model_dump(mode="json"),
            **score.model_dump(mode="json", exclude={"transaction_id"}),
            "explanation": json.dumps([item.model_dump() for item in score.explanation]),
            "feature_snapshot": json.dumps(score.feature_snapshot),
        }

    def save_batch(self, batch: WriteBatch) -> None:
        """Commit scored/rejected records, metrics, and outbox rows atomically."""
        self._ensure_open(wait=True)
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                if batch.scores:
                    cursor.executemany(
                        SCORE_UPSERT,
                        [self._score_values(event, score) for event, score in batch.scores],
                    )
                if batch.rejections:
                    cursor.executemany(
                        """
                        INSERT INTO rejected_transactions
                            (source_topic, error_type, error_message, transaction_id, payload)
                        VALUES (%s, %s, %s, %s, %s::jsonb)
                        """,
                        [
                            (
                                rejection.source_topic,
                                rejection.error_type,
                                rejection.error_message,
                                rejection.transaction_id,
                                json.dumps(rejection.payload, default=str),
                            )
                            for rejection in batch.rejections
                        ],
                    )
                if batch.metrics:
                    cursor.executemany(
                        """
                        INSERT INTO pipeline_metrics (metric_name, metric_value, labels)
                        VALUES (%s, %s, %s::jsonb)
                        """,
                        [
                            (name, value, json.dumps(labels))
                            for name, value, labels in batch.metrics
                        ],
                    )
                if batch.outbox:
                    cursor.executemany(
                        """
                        INSERT INTO kafka_outbox (dedupe_key, topic, message_key, payload)
                        VALUES (%s, %s, %s, %s::jsonb)
                        ON CONFLICT (dedupe_key) DO NOTHING
                        """,
                        [
                            (row.dedupe_key, row.topic, row.message_key, json.dumps(row.payload))
                            for row in batch.outbox
                        ],
                    )

    def save_score(self, event: TransactionEvent, score: ScoreResponse) -> None:
        self.save_batch(WriteBatch(scores=[(event, score)]))

    def save_rejection(self, rejection: RejectedEvent) -> None:
        self.save_batch(WriteBatch(rejections=[rejection]))

    def record_metric(self, name: str, value: float, labels: dict | None = None) -> None:
        self.save_batch(WriteBatch(metrics=[(name, value, labels or {})]))

    def claim_outbox(self, batch_size: int, lease_seconds: int = 300) -> tuple[str, list[dict]]:
        self._ensure_open(wait=True)
        token = str(uuid.uuid4())
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                WITH candidates AS (
                    SELECT outbox_id FROM kafka_outbox
                    WHERE published_at IS NULL AND available_at <= NOW()
                      AND (claimed_at IS NULL OR claimed_at < NOW() - make_interval(secs => %s))
                    ORDER BY outbox_id FOR UPDATE SKIP LOCKED LIMIT %s
                )
                UPDATE kafka_outbox AS target
                SET claimed_at = NOW(), claim_token = %s, attempts = attempts + 1
                FROM candidates WHERE target.outbox_id = candidates.outbox_id
                RETURNING target.outbox_id, target.topic, target.message_key, target.payload
                """,
                (lease_seconds, batch_size, token),
            ).fetchall()
        return token, [
            {"outbox_id": row[0], "topic": row[1], "message_key": row[2], "payload": row[3]}
            for row in rows
        ]

    def mark_outbox_published(self, outbox_id: int, token: str) -> None:
        self._ensure_open(wait=True)
        with self.pool.connection() as connection:
            connection.execute(
                """
                UPDATE kafka_outbox SET published_at = NOW(), claimed_at = NULL,
                    claim_token = NULL, last_error = NULL
                WHERE outbox_id = %s AND claim_token = %s
                """,
                (outbox_id, token),
            )

    def release_outbox(self, outbox_id: int, token: str, error: str) -> None:
        self._ensure_open(wait=True)
        with self.pool.connection() as connection:
            connection.execute(
                """
                UPDATE kafka_outbox SET claimed_at = NULL, claim_token = NULL, last_error = %s,
                    available_at = NOW() + LEAST(
                        INTERVAL '5 minutes', attempts * INTERVAL '5 seconds'
                    )
                WHERE outbox_id = %s AND claim_token = %s
                """,
                (error[:500], outbox_id, token),
            )
