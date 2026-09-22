from __future__ import annotations

import hashlib
import json
import logging
import signal
import time

import httpx
from confluent_kafka import KafkaError, KafkaException, TopicPartition
from pydantic import ValidationError

from lossguard.alerts import send_high_risk_alert
from lossguard.config import get_settings
from lossguard.constants import RAW_TOPIC, REJECTED_TOPIC, SCORED_TOPIC
from lossguard.database import OutboxRecord, TransactionRepository, WriteBatch
from lossguard.kafka import build_consumer
from lossguard.schemas import RejectedEvent, ScoreResponse, TransactionEvent

LOGGER = logging.getLogger("lossguard.consumer")
RUNNING = True
DEAD_LETTER_SAFE_FIELDS = {
    "transaction_id": 64,
    "event_time": 40,
    "merchant_category": 64,
    "channel": 32,
}


def stop(*_) -> None:
    global RUNNING
    RUNNING = False


def _safe_rejection_error(error: Exception) -> str:
    if isinstance(error, ValidationError):
        known_fields = set(TransactionEvent.model_fields)
        issues = [
            {
                "type": issue["type"],
                "location": [
                    str(part)
                    if isinstance(part, int) or str(part) in known_fields
                    else "unknown_field"
                    for part in issue["loc"]
                ],
            }
            for issue in error.errors(include_url=False, include_context=False, include_input=False)
        ]
        return json.dumps({"validation_issues": issues}, separators=(",", ":"))[:2000]
    if isinstance(error, json.JSONDecodeError):
        return f"Invalid JSON at byte offset {error.pos}"
    return f"Rejected by {type(error).__name__}"


def _safe_payload_summary(payload, raw_value: bytes | None) -> dict:
    if raw_value is None:
        raw_value = json.dumps(payload, default=str, separators=(",", ":")).encode()
    safe_fields: dict[str, str | int | float | bool | None] = {}
    if isinstance(payload, dict):
        for field, max_length in DEAD_LETTER_SAFE_FIELDS.items():
            value = payload.get(field)
            if isinstance(value, str):
                safe_fields[field] = value[:max_length]
            elif isinstance(value, (int, float, bool)) or value is None:
                safe_fields[field] = value
    return {
        "payload_sha256": hashlib.sha256(raw_value).hexdigest(),
        "payload_bytes": len(raw_value),
        "safe_fields": safe_fields,
    }


def rejection_from_error(
    payload,
    error: Exception,
    raw_value: bytes | None = None,
) -> RejectedEvent:
    safe_payload = _safe_payload_summary(payload, raw_value)
    transaction_id = safe_payload["safe_fields"].get("transaction_id")
    return RejectedEvent(
        source_topic=RAW_TOPIC,
        error_type=type(error).__name__,
        error_message=_safe_rejection_error(error),
        transaction_id=str(transaction_id) if transaction_id else None,
        payload=safe_payload,
    )


def score_with_retry(
    client: httpx.Client,
    event: TransactionEvent,
    api_key: str,
    attempts: int,
    backoff_seconds: float,
    retry_metric=None,
) -> ScoreResponse:
    if attempts < 1:
        raise ValueError("attempts must be at least one")
    for attempt in range(1, attempts + 1):
        try:
            response = client.post(
                "/score",
                json=event.model_dump(mode="json"),
                headers={"X-API-Key": api_key},
            )
            response.raise_for_status()
            return ScoreResponse.model_validate(response.json())
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
            if not retryable or attempt == attempts:
                raise
        except httpx.TransportError:
            if attempt == attempts:
                raise
        if retry_metric is not None:
            retry_metric("scoring_api_retries", 1, {"attempt": attempt + 1})
        time.sleep(backoff_seconds * attempt)
    raise RuntimeError("Scoring API retry loop exited unexpectedly")


def run() -> None:
    settings = get_settings()
    repository = TransactionRepository(
        settings.database_url,
        min_pool_size=settings.postgres_pool_min_size,
        max_pool_size=settings.postgres_pool_max_size,
    )
    repository.wait_until_ready()
    consumer = build_consumer(settings.kafka_bootstrap_servers)
    consumer.subscribe([RAW_TOPIC])
    processed = rejected = 0
    batch = WriteBatch()
    messages = []
    pending_alerts: list[tuple[TransactionEvent, ScoreResponse]] = []
    last_flush = time.monotonic()

    def flush() -> None:
        nonlocal batch, messages, pending_alerts, last_flush
        if not messages:
            return
        repository.save_batch(batch)
        offsets: dict[tuple[str, int], TopicPartition] = {}
        for source_message in messages:
            key = (source_message.topic(), source_message.partition())
            offsets[key] = TopicPartition(*key, source_message.offset() + 1)
        # Source offsets move only after the PostgreSQL transaction and outbox row commit.
        consumer.commit(offsets=list(offsets.values()), asynchronous=False)
        for alert_event, alert_score in pending_alerts:
            if send_high_risk_alert(
                alert_event,
                alert_score,
                settings.slack_webhook_url,
                settings.slack_high_risk_threshold,
                settings.dashboard_public_url,
                client,
            ):
                repository.record_metric(
                    "high_risk_alerts_sent", 1, {"decision": alert_score.decision}
                )
        batch = WriteBatch()
        messages = []
        pending_alerts = []
        last_flush = time.monotonic()

    with httpx.Client(base_url=settings.scoring_api_url, timeout=15.0) as client:
        try:
            while RUNNING:
                message = consumer.poll(1.0)
                if message is None:
                    flush_due = (
                        messages
                        and time.monotonic() - last_flush >= settings.consumer_flush_seconds
                    )
                    if flush_due:
                        flush()
                    continue
                if message.error():
                    if message.error().code() != KafkaError._PARTITION_EOF:
                        LOGGER.error("Kafka consumer error: %s", message.error())
                    continue
                payload = None
                raw_value = message.value()
                try:
                    payload = json.loads(raw_value)
                    event = TransactionEvent.model_validate(payload)
                except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                    rejection = rejection_from_error(payload, exc, raw_value)
                    message_key = rejection.transaction_id or (
                        f"rejected-{message.partition()}-{message.offset()}"
                    )
                    batch.rejections.append(rejection)
                    batch.metrics.append(
                        ("transactions_rejected", 1, {"error": type(exc).__name__})
                    )
                    batch.outbox.append(
                        OutboxRecord(
                            dedupe_key=(
                                f"rejected:{message.topic()}:{message.partition()}:{message.offset()}"
                            ),
                            topic=REJECTED_TOPIC,
                            message_key=message_key,
                            payload=rejection.model_dump(mode="json"),
                        )
                    )
                    messages.append(message)
                    rejected += 1
                    LOGGER.warning(
                        "Rejected transaction %s (%s)",
                        rejection.transaction_id,
                        rejection.error_type,
                    )
                    if len(batch) >= settings.consumer_write_batch_size:
                        flush()
                    continue

                try:
                    score = score_with_retry(
                        client,
                        event,
                        settings.scoring_api_key,
                        settings.scoring_api_max_attempts,
                        settings.scoring_api_retry_backoff_seconds,
                        repository.record_metric,
                    )
                    batch.scores.append((event, score))
                    batch.metrics.append(("transactions_scored", 1, {"decision": score.decision}))
                    batch.outbox.append(
                        OutboxRecord(
                            dedupe_key=f"scored:{event.transaction_id}:{score.model_version}",
                            topic=SCORED_TOPIC,
                            message_key=event.transaction_id,
                            payload={
                                **event.model_dump(mode="json"),
                                **score.model_dump(mode="json"),
                            },
                        )
                    )
                    messages.append(message)
                    pending_alerts.append((event, score))
                    processed += 1
                except httpx.HTTPError:
                    LOGGER.warning(
                        "Scoring dependency failed for %s; leaving Kafka offset uncommitted",
                        event.transaction_id,
                    )
                    raise
                except (json.JSONDecodeError, ValidationError) as exc:
                    raise RuntimeError(
                        f"Scoring API returned an invalid contract for {event.transaction_id}"
                    ) from exc
                if len(batch) >= settings.consumer_write_batch_size:
                    flush()
                if (processed + rejected) % 500 == 0:
                    LOGGER.info("Processed=%s rejected=%s", processed, rejected)
        finally:
            if messages:
                flush()
            consumer.close()
            repository.close()


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while RUNNING:
        try:
            run()
            return
        except (httpx.HTTPError, KafkaException, RuntimeError, TimeoutError) as exc:
            LOGGER.warning("Consumer dependency unavailable: %s; retrying", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
