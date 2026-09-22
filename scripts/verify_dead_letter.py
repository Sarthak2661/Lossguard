from __future__ import annotations

import csv
import json
import os
import time
import uuid
from pathlib import Path

import psycopg
from confluent_kafka import Consumer, Producer

from lossguard.features import source_row_to_event


def main() -> None:
    kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
    database_url = os.environ["DATABASE_URL"]
    dataset_path = Path(os.getenv("DATASET_PATH", "/data/fraudTest.csv"))
    salt = os.environ["PII_HASH_SALT"]

    with dataset_path.open("r", encoding="utf-8", newline="") as handle:
        payload = source_row_to_event(next(csv.DictReader(handle)), salt)

    transaction_id = f"phase1-malformed-{uuid.uuid4().hex[:12]}"
    payload["transaction_id"] = transaction_id
    payload["amount"] = -5.0

    producer = Producer({"bootstrap.servers": kafka_servers})
    producer.produce(
        "txns.raw",
        key=transaction_id.encode(),
        value=json.dumps(payload).encode(),
    )
    if producer.flush(10):
        raise RuntimeError("Malformed test event was not delivered to txns.raw")

    rejected_rows = scored_rows = 0
    for _ in range(30):
        with psycopg.connect(database_url) as connection:
            rejected_rows = connection.execute(
                "select count(*) from rejected_transactions where transaction_id = %s",
                (transaction_id,),
            ).fetchone()[0]
            scored_rows = connection.execute(
                "select count(*) from scored_transactions where transaction_id = %s",
                (transaction_id,),
            ).fetchone()[0]
        if rejected_rows:
            break
        time.sleep(1)

    consumer = Consumer(
        {
            "bootstrap.servers": kafka_servers,
            "group.id": f"dead-letter-acceptance-{uuid.uuid4().hex}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe(["txns.rejected"])
    found_topic_event = False
    deadline = time.time() + 20
    while time.time() < deadline:
        message = consumer.poll(1)
        if message is None or message.error():
            continue
        if json.loads(message.value()).get("transaction_id") == transaction_id:
            found_topic_event = True
            break
    consumer.close()

    result = {
        "transaction_id": transaction_id,
        "dead_letter_table": rejected_rows == 1,
        "dead_letter_topic": found_topic_event,
        "main_table_rows": scored_rows,
    }
    print(json.dumps(result, indent=2))
    if not (result["dead_letter_table"] and found_topic_event and scored_rows == 0):
        raise SystemExit("Malformed-record routing check failed")


if __name__ == "__main__":
    main()
