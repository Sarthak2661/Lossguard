import httpx

from lossguard.alerts import is_high_risk, send_high_risk_alert, slack_message
from lossguard.features import source_row_to_event
from lossguard.schemas import ScoreResponse, TransactionEvent
from tests.test_privacy_and_features import SOURCE_ROW


def score_response(probability: float) -> ScoreResponse:
    return ScoreResponse(
        transaction_id=SOURCE_ROW["trans_num"],
        fraud_probability=probability,
        decision="decline",
        verify_threshold=0.25,
        decline_threshold=0.70,
        expected_cost_approve=100,
        expected_cost_verify=20,
        expected_cost_decline=5,
        model_version="test-model",
        explanation=[],
        feature_snapshot={},
    )


def test_high_risk_boundary_and_privacy_safe_message():
    event = TransactionEvent.model_validate(source_row_to_event(SOURCE_ROW, "test-salt"))
    score = score_response(0.91)
    payload = slack_message(event, score, 0.90, "http://localhost:8501")

    assert is_high_risk(score, 0.90)
    assert SOURCE_ROW["cc_num"] not in str(payload)
    assert SOURCE_ROW["first"] not in str(payload)
    assert score.transaction_id in str(payload)


def test_slack_alert_is_optional_and_testable_without_network():
    event = TransactionEvent.model_validate(source_row_to_event(SOURCE_ROW, "test-salt"))
    score = score_response(0.95)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="ok")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert not send_high_risk_alert(event, score, None, 0.90, "http://dashboard", client)
        assert send_high_risk_alert(
            event, score, "https://hooks.slack.test/example", 0.90, "http://dashboard", client
        )

    assert len(requests) == 1
