from __future__ import annotations

import joblib
import numpy as np
import pytest

from lossguard.model_artifact import (
    BUNDLE_SCHEMA_VERSION,
    ModelArtifactError,
    validate_bundle,
    verify_checksum,
    write_checksum,
)


class Model:
    def predict_proba(self, _matrix):
        return np.asarray([[0.5, 0.5]])


class Calibrator:
    def predict(self, probabilities):
        return np.asarray(probabilities)


class Preprocessor:
    def transform(self, matrix):
        return matrix


def valid_bundle() -> dict:
    return {
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "model": Model(),
        "calibrator": Calibrator(),
        "preprocessor": Preprocessor(),
        "feature_names": ["amount"],
        "model_features": ["amount"],
        "category_thresholds": {},
        "global_thresholds": {"verify": 0.2, "decline": 0.7},
        "model_version": "test-v1",
    }


def test_model_artifact_checksum_round_trip_and_tamper_detection(tmp_path) -> None:
    artifact = tmp_path / "model.joblib"
    joblib.dump(valid_bundle(), artifact)

    digest = write_checksum(artifact)

    assert verify_checksum(artifact) == digest
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(ModelArtifactError, match="verification failed"):
        verify_checksum(artifact)


def test_model_bundle_contract_requires_calibrator() -> None:
    bundle = valid_bundle()
    del bundle["calibrator"]

    with pytest.raises(ModelArtifactError, match="calibrator"):
        validate_bundle(bundle)


def test_model_artifact_rejects_missing_and_malformed_checksum(tmp_path) -> None:
    artifact = tmp_path / "model.joblib"
    joblib.dump(valid_bundle(), artifact)

    with pytest.raises(ModelArtifactError, match="sidecar is missing"):
        verify_checksum(artifact)
    artifact.with_name("model.joblib.sha256").write_text("not-a-checksum\n", encoding="ascii")
    with pytest.raises(ModelArtifactError, match="sidecar is malformed"):
        verify_checksum(artifact)


def test_model_bundle_rejects_invalid_threshold_order() -> None:
    bundle = valid_bundle()
    bundle["global_thresholds"] = {"verify": 0.8, "decline": 0.2}

    with pytest.raises(ModelArtifactError, match="thresholds are invalid"):
        validate_bundle(bundle)

    bundle["global_thresholds"] = {"verify": 0.2}
    with pytest.raises(ModelArtifactError, match="thresholds are invalid"):
        validate_bundle(bundle)
