import joblib
import numpy as np
import pytest

from apps.scoring_api.model_service import ModelService
from lossguard.features import source_row_to_event
from lossguard.model_artifact import ModelArtifactError, write_checksum
from lossguard.schemas import TransactionEvent
from tests.test_model_artifact import valid_bundle
from tests.test_privacy_and_features import SOURCE_ROW


def test_service_has_explicit_fallback_when_artifact_missing(tmp_path):
    service = ModelService(str(tmp_path / "missing.joblib"))
    event = TransactionEvent.model_validate(source_row_to_event(SOURCE_ROW, "test-salt"))
    response = service.score(event)
    assert response.model_version == "heuristic-v0"
    assert response.decision in {"approve", "verify", "decline"}
    assert 0 <= response.fraud_probability <= 1
    assert response.explanation


class FixedModel:
    def predict_proba(self, _matrix):
        return np.asarray([[0.2, 0.8]])


class FixedCalibrator:
    def predict(self, _probabilities):
        return np.asarray([0.25])


class FixedPreprocessor:
    def transform(self, _frame):
        return np.asarray([[1.0]])


class FailingExplainer:
    def shap_values(self, _matrix):
        raise RuntimeError("synthetic explanation failure")


def test_service_uses_calibrated_probability_and_emits_shap_failure_metric(tmp_path):
    metrics = []
    service = ModelService(str(tmp_path / "missing.joblib"), lambda *args: metrics.append(args))
    service.bundle = {
        "model": FixedModel(),
        "calibrator": FixedCalibrator(),
        "preprocessor": FixedPreprocessor(),
        "feature_names": ["amount"],
        "model_version": "test-model",
        "global_thresholds": {"verify": 0.2, "decline": 0.7},
        "category_thresholds": {},
    }
    service._explainer = FailingExplainer()
    event = TransactionEvent.model_validate(source_row_to_event(SOURCE_ROW, "test-salt"))

    response = service.score(event)

    assert response.fraud_probability == 0.25
    assert response.explanation == []
    assert metrics == [
        (
            "shap_explanation_failures",
            1,
            {"model_version": "test-model", "error_type": "RuntimeError"},
        )
    ]


def test_service_loads_only_checksum_verified_bundle_and_preserves_last_good(tmp_path):
    artifact = tmp_path / "model.joblib"
    joblib.dump(valid_bundle(), artifact)
    write_checksum(artifact)
    service = ModelService(str(artifact))

    assert service.is_model_ready
    assert service.artifact_sha256 is not None

    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(ModelArtifactError):
        service.reload(raise_on_error=True)

    assert service.is_model_ready
    assert service.model_version == "test-v1"
