from __future__ import annotations

from lossguard.database import OutboxRecord, TransactionRepository, WriteBatch
from lossguard.features import source_row_to_event
from lossguard.schemas import RejectedEvent, ScoreResponse, TransactionEvent
from tests.test_privacy_and_features import SOURCE_ROW


class Cursor:
    def __init__(self, executions) -> None:
        self.executions = executions

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def executemany(self, query, values):
        self.executions.append((query, list(values)))


class Connection:
    def __init__(self) -> None:
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query, values=None):
        self.executions.append((query, values))
        return self

    def cursor(self):
        return Cursor(self.executions)


class Pool:
    def __init__(self, connection) -> None:
        self._connection = connection
        self.closed = True

    def open(self, **_kwargs):
        self.closed = False

    def connection(self):
        return self._connection

    def close(self):
        self.closed = True


def event_and_score() -> tuple[TransactionEvent, ScoreResponse]:
    event = TransactionEvent.model_validate(source_row_to_event(SOURCE_ROW, "test-salt"))
    score = ScoreResponse(
        transaction_id=event.transaction_id,
        fraud_probability=0.2,
        decision="verify",
        verify_threshold=0.1,
        decline_threshold=0.7,
        expected_cost_approve=1.0,
        expected_cost_verify=0.5,
        expected_cost_decline=2.0,
        model_version="test",
        explanation=[],
        feature_snapshot={"amount": event.amount},
    )
    return event, score


def test_repository_atomically_batches_records_metrics_and_outbox() -> None:
    connection = Connection()
    repository = TransactionRepository("postgresql://test", pool=Pool(connection))
    event, score = event_and_score()
    rejection = RejectedEvent(
        source_topic="txns.raw",
        error_type="ValidationError",
        error_message="invalid",
        transaction_id=event.transaction_id,
        payload={"payload_sha256": "a" * 64},
    )
    batch = WriteBatch(
        scores=[(event, score)],
        rejections=[rejection],
        metrics=[("test_metric", 1, {"source": "unit"})],
        outbox=[OutboxRecord("score:test", "txns.scored", event.transaction_id, {"ok": True})],
    )

    repository.wait_until_ready(attempts=1)
    repository.save_batch(batch)

    queries = [execution[0] for execution in connection.executions]
    assert any("SELECT 1" in query for query in queries)
    score_upsert = next(
        query for query in queries if "ON CONFLICT (transaction_id) DO UPDATE" in query
    )
    for field in (
        "event_time",
        "customer_id",
        "merchant",
        "merchant_category",
        "channel",
        "amount",
        "order_margin_pct",
        "customer_ltv_band",
        "fraud_label",
    ):
        assert f"{field} = EXCLUDED.{field}" in score_upsert
    assert any("INSERT INTO rejected_transactions" in query for query in queries)
    assert any("INSERT INTO pipeline_metrics" in query for query in queries)
    assert any("INSERT INTO kafka_outbox" in query for query in queries)
