from __future__ import annotations

from lossguard.database import TransactionRepository
from lossguard.features import source_row_to_event
from lossguard.schemas import RejectedEvent, ScoreResponse, TransactionEvent
from tests.test_privacy_and_features import SOURCE_ROW


class Connection:
    def __init__(self) -> None:
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query, values=None):
        self.executions.append((query, values))
        return self


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


def test_repository_writes_scores_rejections_metrics_and_readiness(monkeypatch) -> None:
    connection = Connection()
    monkeypatch.setattr("lossguard.database.psycopg.connect", lambda _url: connection)
    repository = TransactionRepository("postgresql://test")
    event, score = event_and_score()
    rejection = RejectedEvent(
        source_topic="txns.raw",
        error_type="ValidationError",
        error_message="invalid",
        transaction_id=event.transaction_id,
        payload={"payload_sha256": "a" * 64},
    )

    repository.wait_until_ready(attempts=1)
    repository.save_score(event, score)
    repository.save_rejection(rejection)
    repository.record_metric("test_metric", 1, {"source": "unit"})

    queries = [execution[0] for execution in connection.executions]
    assert any("SELECT 1" in query for query in queries)
    assert any("ON CONFLICT (transaction_id) DO UPDATE" in query for query in queries)
    assert any("INSERT INTO rejected_transactions" in query for query in queries)
    assert any("INSERT INTO pipeline_metrics" in query for query in queries)
