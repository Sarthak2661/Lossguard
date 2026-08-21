from apps.scoring_api.model_service import ModelService
from lossguard.features import source_row_to_event
from lossguard.schemas import TransactionEvent
from tests.test_privacy_and_features import SOURCE_ROW


def test_service_has_explicit_fallback_when_artifact_missing(tmp_path):
    service = ModelService(str(tmp_path / "missing.joblib"))
    event = TransactionEvent.model_validate(source_row_to_event(SOURCE_ROW, "test-salt"))
    response = service.score(event)
    assert response.model_version == "heuristic-v0"
    assert response.decision in {"approve", "verify", "decline"}
    assert 0 <= response.fraud_probability <= 1
    assert response.explanation
