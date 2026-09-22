from __future__ import annotations

import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import psycopg
import pytest
from confluent_kafka import Consumer
from confluent_kafka.admin import AdminClient, NewTopic

from apps.consumer.main import score_with_retry
from apps.outbox_publisher.main import publish_once
from lossguard.database import OutboxRecord, TransactionRepository, WriteBatch
from lossguard.features import source_row_to_event
from lossguard.kafka import build_producer, publish_json
from lossguard.schemas import ScoreResponse, TransactionEvent
from tests.test_privacy_and_features import SOURCE_ROW

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION_TESTS") != "1",
        reason="set RUN_INTEGRATION_TESTS=1 with the core Compose dependencies running",
    ),
]


def local_database_url() -> str:
    return os.environ["DATABASE_URL"].replace("@localhost:", "@127.0.0.1:")


def sample_event(transaction_id: str | None = None) -> TransactionEvent:
    payload = source_row_to_event(SOURCE_ROW, "integration-test-salt")
    if transaction_id:
        payload["transaction_id"] = transaction_id
    return TransactionEvent.model_validate(payload)


def sample_score(event: TransactionEvent) -> ScoreResponse:
    return ScoreResponse(
        transaction_id=event.transaction_id,
        fraud_probability=0.25,
        decision="verify",
        verify_threshold=0.2,
        decline_threshold=0.7,
        expected_cost_approve=25.0,
        expected_cost_verify=10.0,
        expected_cost_decline=15.0,
        realized_policy_cost=5.0,
        baseline_cost=25.0,
        estimated_savings=20.0,
        model_version="integration-v1",
        explanation=[],
        feature_snapshot={"amount": event.amount},
    )


def test_kafka_publish_is_broker_confirmed_and_consumable() -> None:
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:19092")
    topic = f"lossguard.integration.{uuid.uuid4().hex}"
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])[topic].result(10)
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": f"integration-{uuid.uuid4().hex}",
            "auto.offset.reset": "earliest",
        }
    )
    try:
        producer = build_producer(bootstrap_servers)
        publish_json(producer, topic, "integration-key", {"status": "confirmed"})
        consumer.subscribe([topic])
        deadline = time.monotonic() + 10
        payload = None
        while time.monotonic() < deadline:
            message = consumer.poll(1)
            if message is not None and not message.error():
                payload = json.loads(message.value())
                break
        assert payload == {"status": "confirmed"}
    finally:
        consumer.close()
        admin.delete_topics([topic], operation_timeout=10)[topic].result(10)


def test_postgres_duplicate_processing_is_idempotent() -> None:
    database_url = local_database_url()
    transaction_id = f"integration-{uuid.uuid4().hex}"
    event = sample_event(transaction_id)
    score = sample_score(event)
    repository = TransactionRepository(database_url)
    try:
        repository.save_score(event, score)
        updated_band = "high" if event.customer_ltv_band != "high" else "low"
        updated_event = event.model_copy(update={"customer_ltv_band": updated_band})
        repository.save_score(updated_event, score)
        with psycopg.connect(database_url) as connection:
            count, stored_band = connection.execute(
                """
                SELECT count(*), max(customer_ltv_band)
                FROM scored_transactions
                WHERE transaction_id = %s
                """,
                (transaction_id,),
            ).fetchone()
        assert count == 1
        assert stored_band == updated_band
    finally:
        repository.close()
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "DELETE FROM scored_transactions WHERE transaction_id = %s",
                (transaction_id,),
            )


def test_transactional_outbox_is_published_and_marked() -> None:
    database_url = local_database_url()
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:19092")
    dedupe_key = f"integration-outbox-{uuid.uuid4().hex}"
    repository = TransactionRepository(database_url)
    try:
        repository.save_batch(
            WriteBatch(
                outbox=[
                    OutboxRecord(dedupe_key, "txns.scored", dedupe_key, {"integration_test": True})
                ]
            )
        )
        assert publish_once(repository, build_producer(bootstrap_servers), 100) >= 1
        with psycopg.connect(database_url) as connection:
            published = connection.execute(
                "SELECT published_at IS NOT NULL FROM kafka_outbox WHERE dedupe_key = %s",
                (dedupe_key,),
            ).fetchone()[0]
        assert published
    finally:
        repository.close()
        with psycopg.connect(database_url) as connection:
            connection.execute("DELETE FROM kafka_outbox WHERE dedupe_key = %s", (dedupe_key,))


def test_scoring_api_retries_transient_http_failures() -> None:
    event = sample_event()
    score_payload = sample_score(event).model_dump(mode="json")

    class FlakyHandler(BaseHTTPRequestHandler):
        requests = 0

        def do_POST(self) -> None:
            type(self).requests += 1
            request_length = int(self.headers.get("content-length", "0"))
            self.rfile.read(request_length)
            if type(self).requests < 3:
                self.send_response(503)
                self.end_headers()
                return
            body = json.dumps(score_payload).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), FlakyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}") as client:
            response = score_with_retry(client, event, "integration-key", 3, 0)
        assert response.transaction_id == event.transaction_id
        assert FlakyHandler.requests == 3
    finally:
        server.shutdown()
        thread.join(timeout=5)
