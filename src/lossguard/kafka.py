from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable

from confluent_kafka import Consumer, KafkaException, Producer

LOGGER = logging.getLogger(__name__)


def build_producer(bootstrap_servers: str) -> Producer:
    return Producer(
        {
            "bootstrap.servers": bootstrap_servers,
            "client.id": "lossguard-producer",
            "enable.idempotence": True,
            "acks": "all",
            "compression.type": "snappy",
        }
    )


def build_consumer(bootstrap_servers: str, group_id: str = "lossguard-scorers") -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )


def delivery_report(error, message) -> None:
    if error is not None:
        LOGGER.error("Kafka delivery failed: %s", error)


def publish_json(producer: Producer, topic: str, key: str, payload: dict) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), default=str).encode()
    while True:
        try:
            producer.produce(topic, key=key.encode(), value=encoded, on_delivery=delivery_report)
            producer.poll(0)
            return
        except BufferError:
            producer.poll(0.2)


def wait_for_kafka(factory: Callable[[], Producer], attempts: int = 30) -> Producer:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            producer = factory()
            producer.list_topics(timeout=3)
            return producer
        except KafkaException as exc:
            last_error = exc
            LOGGER.warning("Kafka not ready (attempt %s/%s)", attempt + 1, attempts)
            time.sleep(min(1 + attempt * 0.2, 5))
    raise RuntimeError("Kafka did not become ready") from last_error
