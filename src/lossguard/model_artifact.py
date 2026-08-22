from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import Any

BUNDLE_SCHEMA_VERSION = 2
REQUIRED_BUNDLE_KEYS = {
    "bundle_schema_version",
    "model",
    "calibrator",
    "preprocessor",
    "feature_names",
    "model_features",
    "category_thresholds",
    "global_thresholds",
    "model_version",
}


class ModelArtifactError(ValueError):
    pass


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_path(bundle_path: str | Path) -> Path:
    path = Path(bundle_path)
    return path.with_name(f"{path.name}.sha256")


def write_checksum(bundle_path: str | Path) -> str:
    path = Path(bundle_path)
    digest = sha256_file(path)
    checksum_path(path).write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return digest


def verify_checksum(bundle_path: str | Path) -> str:
    path = Path(bundle_path)
    sidecar = checksum_path(path)
    if not sidecar.exists():
        raise ModelArtifactError(f"Model checksum sidecar is missing: {sidecar}")
    expected = sidecar.read_text(encoding="ascii").split(maxsplit=1)[0].lower()
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise ModelArtifactError(f"Model checksum sidecar is malformed: {sidecar}")
    actual = sha256_file(path)
    if not hmac.compare_digest(actual, expected):
        raise ModelArtifactError(f"Model checksum verification failed: {path}")
    return actual


def validate_bundle(bundle: Any) -> dict:
    if not isinstance(bundle, dict):
        raise ModelArtifactError("Model bundle must be a dictionary")
    missing = REQUIRED_BUNDLE_KEYS - bundle.keys()
    if missing:
        raise ModelArtifactError(f"Model bundle is missing keys: {sorted(missing)}")
    if bundle["bundle_schema_version"] != BUNDLE_SCHEMA_VERSION:
        raise ModelArtifactError(
            f"Unsupported model bundle schema version: {bundle['bundle_schema_version']}"
        )
    if not hasattr(bundle["model"], "predict_proba"):
        raise ModelArtifactError("Model bundle classifier does not implement predict_proba")
    if not hasattr(bundle["calibrator"], "predict"):
        raise ModelArtifactError("Model bundle calibrator does not implement predict")
    if not hasattr(bundle["preprocessor"], "transform"):
        raise ModelArtifactError("Model bundle preprocessor does not implement transform")
    if not isinstance(bundle["feature_names"], list) or not bundle["feature_names"]:
        raise ModelArtifactError("Model bundle feature_names must be a non-empty list")
    if not isinstance(bundle["model_features"], list) or not bundle["model_features"]:
        raise ModelArtifactError("Model bundle model_features must be a non-empty list")
    if not isinstance(bundle["model_version"], str) or not bundle["model_version"]:
        raise ModelArtifactError("Model bundle model_version must be a non-empty string")
    thresholds = bundle["global_thresholds"]
    try:
        thresholds_valid = (
            isinstance(thresholds, dict)
            and 0 <= float(thresholds["verify"]) < float(thresholds["decline"]) <= 1
        )
    except (KeyError, TypeError, ValueError):
        thresholds_valid = False
    if not thresholds_valid:
        raise ModelArtifactError("Model bundle global thresholds are invalid")
    return bundle
