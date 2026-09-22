from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.dashboard.data import load_latest_model_health


class _Rows:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _Connection:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _query):
        return _Rows(self.row)


class _Engine:
    def __init__(self, row):
        self.row = row

    def connect(self):
        return _Connection(self.row)


def test_model_health_marks_old_report_stale() -> None:
    row = {
        "generated_at": datetime.now(UTC) - timedelta(minutes=10),
        "health_status": "ok",
    }
    result = load_latest_model_health(_Engine(row), max_age_seconds=60)

    assert result is not None
    assert result["effective_health_status"] == "stale"
    assert result["is_stale"] is True


def test_model_health_preserves_fresh_error() -> None:
    row = {"generated_at": datetime.now(UTC), "health_status": "error"}
    result = load_latest_model_health(_Engine(row), max_age_seconds=60)

    assert result is not None
    assert result["effective_health_status"] == "error"
    assert result["is_stale"] is False


def test_model_health_handles_no_report() -> None:
    assert load_latest_model_health(_Engine(None)) is None
