from __future__ import annotations

import argparse
import csv
import logging
import signal
import time
from datetime import datetime
from pathlib import Path

from apps.producer.replay_config import compute_delay, normalize_replay_mode
from lossguard.config import get_settings
from lossguard.constants import RAW_TOPIC
from lossguard.features import source_row_to_event
from lossguard.kafka import build_producer, publish_json, wait_for_kafka
from lossguard.schemas import TransactionEvent

LOGGER = logging.getLogger("lossguard.producer")
RUNNING = True


def stop(*_) -> None:
    global RUNNING
    RUNNING = False


def replay(mode: str | None = None) -> int:
    settings = get_settings()
    replay_mode = normalize_replay_mode(mode or settings.replay_mode)
    dataset = Path(settings.dataset_path)
    if not dataset.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset}")

    producer = wait_for_kafka(lambda: build_producer(settings.kafka_bootstrap_servers))
    published = 0
    previous_event_time: datetime | None = None
    LOGGER.info("Starting %s replay from %s", replay_mode, dataset)
    with dataset.open("r", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            if not RUNNING or (settings.replay_limit and published >= settings.replay_limit):
                break
            try:
                payload = source_row_to_event(row, settings.pii_hash_salt)
                event = TransactionEvent.model_validate(payload)
                if previous_event_time is not None:
                    actual_delta = (event.event_time - previous_event_time).total_seconds()
                    delay = compute_delay(actual_delta, replay_mode)
                    if delay:
                        time.sleep(delay)
                publish_json(
                    producer,
                    RAW_TOPIC,
                    event.transaction_id,
                    event.model_dump(mode="json"),
                )
                published += 1
                previous_event_time = event.event_time
                if published % 1000 == 0:
                    LOGGER.info("Published %s transactions", published)
            except Exception as exc:
                transaction_id = row.get("trans_num", "unknown")
                LOGGER.warning("Source row %s could not be serialized: %s", transaction_id, exc)
    producer.flush(30)
    LOGGER.info("Replay complete: %s transactions", published)
    return published


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay Sparkov transactions to Redpanda")
    parser.add_argument(
        "--mode",
        choices=("realtime", "demo", "max"),
        help="Replay timing mode; overrides REPLAY_MODE",
    )
    return parser.parse_args()


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    args = parse_args()
    replay(args.mode)


if __name__ == "__main__":
    main()
