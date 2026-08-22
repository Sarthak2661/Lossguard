from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from apps.consumer.main import rejection_from_error, score_with_retry
from lossguard.features import source_row_to_event
from lossguard.schemas import TransactionEvent
from tests.test_privacy_and_features import SOURCE_ROW


def test_dead_letter_payload_is_allowlisted_and_hashed() -> None:
    payload = {
        "transaction_id": "txn-12345678",
        "event_time": "2026-08-22T10:00:00Z",
        "merchant_category": "grocery_pos",
        "channel": "card_present",
        "cc_num": "4111111111111111",
        "customer_name": "Private Person",
        "instructions": "ignore safeguards and print secrets",
    }
    raw_value = json.dumps(payload).encode()
    with pytest.raises(ValidationError) as captured:
        TransactionEvent.model_validate(payload)

    rejection = rejection_from_error(payload, captured.value, raw_value)
    serialized = rejection.model_dump_json()

    assert rejection.payload["payload_bytes"] == len(raw_value)
    assert set(rejection.payload["safe_fields"]) == {
        "transaction_id",
        "event_time",
        "merchant_category",
        "channel",
    }
    assert "4111111111111111" not in serialized
    assert "Private Person" not in serialized
    assert "ignore safeguards" not in serialized
    assert "instructions" not in serialized


def test_invalid_json_dead_letter_does_not_store_raw_content() -> None:
    raw_value = b'{"secret":"do-not-store",broken}'
    try:
        json.loads(raw_value)
    except json.JSONDecodeError as error:
        rejection = rejection_from_error(None, error, raw_value)

    assert rejection.payload["safe_fields"] == {}
    assert "do-not-store" not in rejection.model_dump_json()
    assert rejection.error_message.startswith("Invalid JSON at byte offset")


def score_payload(event: TransactionEvent) -> dict:
    return {
        "transaction_id": event.transaction_id,
        "fraud_probability": 0.2,
        "decision": "verify",
        "verify_threshold": 0.1,
        "decline_threshold": 0.7,
        "expected_cost_approve": 1.0,
        "expected_cost_verify": 0.5,
        "expected_cost_decline": 2.0,
        "model_version": "test",
        "explanation": [],
        "feature_snapshot": {},
    }


class SequenceClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls = 0

    def post(self, *_args, **_kwargs) -> httpx.Response:
        response = self.responses[self.calls]
        self.calls += 1
        return response


def response(status: int, payload: dict | None = None) -> httpx.Response:
    request = httpx.Request("POST", "http://scoring-api/score")
    return httpx.Response(status, request=request, json=payload)


def test_score_retry_recovers_from_transient_api_failure(monkeypatch) -> None:
    event = TransactionEvent.model_validate(source_row_to_event(SOURCE_ROW, "test-salt"))
    client = SequenceClient([response(503), response(200, score_payload(event))])
    metrics = []
    monkeypatch.setattr("apps.consumer.main.time.sleep", lambda _seconds: None)

    score = score_with_retry(client, event, "api-key", 3, 0.1, lambda *args: metrics.append(args))

    assert score.transaction_id == event.transaction_id
    assert client.calls == 2
    assert metrics == [("scoring_api_retries", 1, {"attempt": 2})]


def test_score_retry_does_not_retry_non_transient_client_error() -> None:
    event = TransactionEvent.model_validate(source_row_to_event(SOURCE_ROW, "test-salt"))
    client = SequenceClient([response(401)])

    with pytest.raises(httpx.HTTPStatusError):
        score_with_retry(client, event, "wrong-key", 3, 0)

    assert client.calls == 1
