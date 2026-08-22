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


def publish_json(
    producer: Producer,
    topic: str,
    key: str,
    payload: dict,
    timeout_seconds: float = 10.0,
) -> None:
    """Publish one JSON record and return only after broker acknowledgement."""
    encoded = json.dumps(payload, separators=(",", ":"), default=str).encode()
    delivery_error = None
    delivered = False
    deadline = time.monotonic() + timeout_seconds

    def delivery_report(error, _message) -> None:
        nonlocal delivered, delivery_error
        delivery_error = error
        delivered = True

    while True:
        try:
            producer.produce(topic, key=key.encode(), value=encoded, on_delivery=delivery_report)
            break
        except BufferError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Kafka producer queue remained full for {topic}") from None
            producer.poll(min(0.2, remaining))

    while not delivered:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Kafka delivery confirmation timed out for {topic}")
        producer.poll(min(0.2, remaining))

    if delivery_error is not None:
        raise KafkaException(delivery_error)


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
