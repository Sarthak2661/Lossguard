from __future__ import annotations

import logging
import os
import signal
import time

from confluent_kafka import KafkaException

from lossguard.config import get_settings
from lossguard.database import TransactionRepository
from lossguard.kafka import build_producer, publish_json, wait_for_kafka

LOGGER = logging.getLogger("lossguard.outbox")
RUNNING = True


def stop(*_) -> None:
    global RUNNING
    RUNNING = False


def publish_once(repository: TransactionRepository, producer, batch_size: int) -> int:
    token, rows = repository.claim_outbox(batch_size)
    for row in rows:
        try:
            publish_json(producer, row["topic"], row["message_key"], row["payload"])
            repository.mark_outbox_published(row["outbox_id"], token)
        except (KafkaException, TimeoutError) as exc:
            repository.release_outbox(row["outbox_id"], token, type(exc).__name__)
            raise
    return len(rows)


def run() -> None:
    settings = get_settings()
    repository = TransactionRepository(
        settings.database_url,
        min_pool_size=settings.postgres_pool_min_size,
        max_pool_size=settings.postgres_pool_max_size,
    )
    repository.wait_until_ready()
    producer = wait_for_kafka(lambda: build_producer(settings.kafka_bootstrap_servers))
    batch_size = int(os.getenv("OUTBOX_BATCH_SIZE", "100"))
    poll_seconds = float(os.getenv("OUTBOX_POLL_SECONDS", "0.25"))
    try:
        while RUNNING:
            published = publish_once(repository, producer, batch_size)
            if not published:
                time.sleep(poll_seconds)
    finally:
        producer.flush(10)
        repository.close()


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while RUNNING:
        try:
            run()
            return
        except (KafkaException, RuntimeError, TimeoutError) as exc:
            LOGGER.warning("Outbox dependency unavailable: %s; retrying", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
