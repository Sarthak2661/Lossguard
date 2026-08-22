import json
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd

from lossguard.features import MODEL_FEATURES
from monitoring.drift_job import (
    DriftConfig,
    drift_summary,
    health_status,
    load_current,
    load_reference,
    model_version,
    persist_result,
    run,
    simulate_distribution_shift,
)


def test_health_status_boundary():
    assert health_status(0.29, 0.30) == "ok"
    assert health_status(0.30, 0.30) == "drifting"


def test_drift_summary_reads_evidently_metric_contract():
    payload = {
        "metrics": [
            {
                "config": {"type": "evidently:metric_v2:DriftedColumnsCount"},
                "value": {"count": 4.0, "share": 0.333333},
            }
        ]
    }
    assert drift_summary(json.loads(json.dumps(payload)), 12) == (4, 12, 0.333333)


def test_simulated_shift_materially_moves_features():
    frame = pd.DataFrame(
        {
            "amount": [10.0, 20.0],
            "log_amount": [2.4, 3.0],
            "distance_km": [2.0, 4.0],
            "transaction_hour": [1, 5],
            "city_population": [1000, 2000],
            "merchant_category": ["home", "travel"],
            "channel": ["card_present", "card_not_present"],
            "customer_ltv_band": ["low", "high"],
        }
    )
    shifted = simulate_distribution_shift(frame)
    assert shifted["amount"].min() > frame["amount"].max()
    assert shifted["distance_km"].min() > frame["distance_km"].max()
    assert shifted["merchant_category"].nunique() == 1


def config(tmp_path) -> DriftConfig:
    return DriftConfig(
        database_url="postgresql://test",
        training_path="training.csv",
        report_dir=str(tmp_path),
        reference_rows=10,
        current_rows=5,
        min_current_rows=3,
        drift_share_threshold=0.3,
        model_metadata_path=str(tmp_path / "metadata.json"),
        pii_hash_salt="test-salt",
    )


def test_drift_config_metadata_and_reference_loading(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://environment")
    monkeypatch.setenv("PII_HASH_SALT", "environment-salt")
    environment_config = DriftConfig.from_env()
    metadata = tmp_path / "metadata.json"
    metadata.write_text('{"model_version":"model-v2"}', encoding="utf-8")
    frame = pd.DataFrame({feature: [1] for feature in MODEL_FEATURES})
    monkeypatch.setattr("monitoring.drift_job.load_training_data", lambda *_args, **_kwargs: frame)
    selected = load_reference(config(tmp_path))

    assert environment_config.database_url == "postgresql://environment"
    assert environment_config.pii_hash_salt == "environment-salt"
    assert model_version(str(metadata)) == "model-v2"
    assert model_version(str(tmp_path / "missing.json")) == "unknown"
    assert selected.shape == (1, 12)


class DriftConnection:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query, values=None):
        self.executions.append((query, values))
        return self

    def fetchall(self):
        return self.rows


def test_current_frame_and_persistence_use_postgres(tmp_path, monkeypatch):
    timestamp = datetime.now(UTC)
    connection = DriftConnection([({"amount": 25.0, "merchant_category": "home"}, timestamp)])
    monkeypatch.setattr("monitoring.drift_job.psycopg.connect", lambda _url: connection)

    current, start, end = load_current(config(tmp_path))
    persist_result(
        config(tmp_path),
        version="v1",
        reference_rows=10,
        current_rows=1,
        drifted_features=2,
        total_features=12,
        drift_share=1 / 6,
        status="ok",
        window_start=start,
        window_end=end,
        json_path="report.json",
        html_path="report.html",
        details={"source": "unit"},
    )

    assert len(current) == 1
    assert start == end == timestamp
    assert any("insert into model_drift_reports" in query for query, _ in connection.executions)


def test_run_persists_insufficient_data_without_generating_report(tmp_path, monkeypatch):
    drift_config = config(tmp_path)
    drift_config = DriftConfig(**{**drift_config.__dict__, "min_current_rows": 10})
    reference = pd.DataFrame({"amount": [1, 2, 3]})
    current = pd.DataFrame({"amount": [1, 2]})
    persisted = []
    monkeypatch.setitem(sys.modules, "evidently", SimpleNamespace(Report=object))
    monkeypatch.setitem(
        sys.modules,
        "evidently.presets",
        SimpleNamespace(DataDriftPreset=object),
    )
    monkeypatch.setattr("monitoring.drift_job.load_reference", lambda _config: reference)
    monkeypatch.setattr(
        "monitoring.drift_job.load_current",
        lambda _config: (current, None, None),
    )
    monkeypatch.setattr(
        "monitoring.drift_job.persist_result",
        lambda *_args, **kwargs: persisted.append(kwargs),
    )

    result = run(drift_config)

    assert result["status"] == "insufficient_data"
    assert persisted[0]["status"] == "insufficient_data"
