from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from lossguard.features import MODEL_FEATURES
from lossguard.model_artifact import verify_checksum
from ml.data import load_training_data
from ml.train import (
    policy_metrics,
    probability_metrics,
    split_training_windows,
    train,
    window_metadata,
)
from tests.test_privacy_and_features import SOURCE_ROW


def training_frame(rows: int = 20) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_time": pd.date_range("2020-01-01", periods=rows, freq="h"),
            "is_fraud": [index % 2 for index in range(rows)],
            "merchant_category": ["home"] * rows,
            "amount": [100.0] * rows,
            "order_margin_pct": [0.2] * rows,
            "customer_ltv_band": ["low"] * rows,
        }
    )


def test_training_windows_are_disjoint_and_chronological() -> None:
    train, calibration, threshold = split_training_windows(training_frame())

    assert [len(train), len(calibration), len(threshold)] == [14, 3, 3]
    assert train["event_time"].max() < calibration["event_time"].min()
    assert calibration["event_time"].max() < threshold["event_time"].min()


def test_training_windows_require_both_classes() -> None:
    frame = training_frame()
    frame["is_fraud"] = 0

    with pytest.raises(ValueError, match="train window"):
        split_training_windows(frame)


def test_probability_and_policy_metrics_are_reported() -> None:
    frame = training_frame(4)
    probabilities = np.asarray([0.1, 0.9, 0.2, 0.8])

    probability = probability_metrics(frame["is_fraud"], probabilities)
    policy = policy_metrics(
        frame,
        probabilities,
        {"verify": 0.3, "decline": 0.7},
        {},
    )

    assert probability["brier_score"] < 0.05
    assert probability["roc_auc"] == 1.0
    assert policy["fraud_intervention_rate"] == 1.0
    assert policy["false_intervention_rate"] == 0.0
    assert policy["decision_counts"] == {"approve": 2, "verify": 0, "decline": 2}
    assert window_metadata(frame)["rows"] == 4


def test_training_data_loader_builds_timestamp_sorted_model_features(tmp_path) -> None:
    later = {**SOURCE_ROW, "trans_date_trans_time": "2020-06-22 12:00:00", "is_fraud": "1"}
    source = tmp_path / "source.csv"
    pd.DataFrame([later, SOURCE_ROW]).to_csv(source, index=False)

    result = load_training_data(str(source), max_rows=None, salt="test-salt")

    assert result["event_time"].is_monotonic_increasing
    assert set(MODEL_FEATURES).issubset(result.columns)
    assert result["is_fraud"].tolist() == [0, 1]


class FakeXGBClassifier:
    def __init__(self, **_kwargs) -> None:
        self.fitted = False

    def fit(self, _matrix, _labels) -> None:
        self.fitted = True

    def predict_proba(self, matrix) -> np.ndarray:
        probabilities = np.linspace(0.05, 0.95, len(matrix))
        return np.column_stack([1 - probabilities, probabilities])


def complete_training_frame(rows: int = 80) -> pd.DataFrame:
    frame = training_frame(rows)
    frame["amount"] = np.linspace(10, 500, rows)
    frame["log_amount"] = np.log1p(frame["amount"])
    frame["distance_km"] = np.linspace(1, 100, rows)
    frame["transaction_hour"] = np.arange(rows) % 24
    frame["transaction_day_of_week"] = np.arange(rows) % 7
    frame["customer_age"] = 30 + np.arange(rows) % 40
    frame["city_population"] = 10_000 + np.arange(rows)
    frame["is_night"] = (frame["transaction_hour"] < 6).astype(int)
    frame["channel"] = np.where(np.arange(rows) % 2, "card_present", "card_not_present")
    return frame


def test_training_pipeline_calibrates_evaluates_and_hashes_artifact(tmp_path, monkeypatch) -> None:
    source_frame = complete_training_frame()
    monkeypatch.setenv("PII_HASH_SALT", "generated-test-salt-value-long-enough")
    monkeypatch.setattr(
        "ml.train.load_training_data", lambda *_args, **_kwargs: source_frame.copy()
    )
    monkeypatch.setitem(sys.modules, "xgboost", SimpleNamespace(XGBClassifier=FakeXGBClassifier))
    artifact = tmp_path / "model.joblib"
    metadata_path = tmp_path / "metadata.json"

    metadata = train(
        "fraudTrain.csv",
        "fraudTest.csv",
        str(artifact),
        str(metadata_path),
        max_rows=None,
    )

    assert metadata["windows"]["train"]["rows"] == 56
    assert metadata["windows"]["calibration"]["rows"] == 12
    assert metadata["windows"]["threshold_validation"]["rows"] == 12
    assert metadata["windows"]["final_test"]["rows"] == 80
    assert metadata["calibration"]["method"] == "isotonic"
    assert "brier_score" in metadata["final_test"]
    assert metadata["artifact"]["sha256"] == verify_checksum(artifact)
    assert metadata_path.exists()
