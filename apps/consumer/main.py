from __future__ import annotations

import json
import logging
import signal
import time

import httpx
from confluent_kafka import KafkaError
from pydantic import ValidationError

from lossguard.alerts import send_high_risk_alert
from lossguard.config import get_settings
from lossguard.constants import RAW_TOPIC, REJECTED_TOPIC, SCORED_TOPIC
from lossguard.database import TransactionRepository
from lossguard.kafka import build_consumer, build_producer, publish_json, wait_for_kafka
from lossguard.schemas import RejectedEvent, ScoreResponse, TransactionEvent

LOGGER = logging.getLogger("lossguard.consumer")
RUNNING = True


def stop(*_) -> None:
    global RUNNING
    RUNNING = False


def rejection_from_error(payload, error: Exception) -> RejectedEvent:
    transaction_id = payload.get("transaction_id") if isinstance(payload, dict) else None
    return RejectedEvent(
        source_topic=RAW_TOPIC,
        error_type=type(error).__name__,
        error_message=str(error)[:2000],
        transaction_id=transaction_id,
        payload=payload,
    )


def run() -> None:
    settings = get_settings()
    repository = TransactionRepository(settings.database_url)
    repository.wait_until_ready()
    producer = wait_for_kafka(lambda: build_producer(settings.kafka_bootstrap_servers))
    consumer = build_consumer(settings.kafka_bootstrap_servers)
    consumer.subscribe([RAW_TOPIC])
    processed = rejected = 0

    with httpx.Client(base_url=settings.scoring_api_url, timeout=15.0) as client:
        try:
            while RUNNING:
                message = consumer.poll(1.0)
                if message is None:
                    continue
                if message.error():
                    if message.error().code() != KafkaError._PARTITION_EOF:
                        LOGGER.error("Kafka consumer error: %s", message.error())
                    continue
                payload = None
                try:
                    payload = json.loads(message.value())
                    event = TransactionEvent.model_validate(payload)
                except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                    rejection = rejection_from_error(payload, exc)
                    repository.save_rejection(rejection)
                    publish_json(
                        producer,
                        REJECTED_TOPIC,
                        rejection.transaction_id or f"rejected-{message.offset()}",
                        rejection.model_dump(mode="json"),
                    )
                    repository.record_metric(
                        "transactions_rejected", 1, {"error": type(exc).__name__}
                    )
                    rejected += 1
                    LOGGER.warning("Rejected transaction %s: %s", rejection.transaction_id, exc)
                    consumer.commit(message=message, asynchronous=False)
                    continue

                try:
                    response = client.post("/score", json=event.model_dump(mode="json"))
                    response.raise_for_status()
                    score = ScoreResponse.model_validate(response.json())
                    repository.save_score(event, score)
                    publish_json(
                        producer,
                        SCORED_TOPIC,
                        event.transaction_id,
                        {**event.model_dump(mode="json"), **score.model_dump(mode="json")},
                    )
                    processed += 1
                    repository.record_metric("transactions_scored", 1, {"decision": score.decision})
                    alert_sent = send_high_risk_alert(
                        event,
                        score,
                        settings.slack_webhook_url,
                        settings.slack_high_risk_threshold,
                        settings.dashboard_public_url,
                        client,
                    )
                    if alert_sent:
                        repository.record_metric(
                            "high_risk_alerts_sent", 1, {"decision": score.decision}
                        )
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
                consumer.commit(message=message, asynchronous=False)
                if (processed + rejected) % 500 == 0:
                    LOGGER.info("Processed=%s rejected=%s", processed, rejected)
        finally:
            producer.flush(10)
            consumer.close()


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
        except (httpx.HTTPError, RuntimeError) as exc:
            LOGGER.warning("Consumer dependency unavailable: %s; retrying", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
