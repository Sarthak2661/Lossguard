from datetime import UTC, datetime, timedelta

from maintenance.retention import clean_report_files, delete_in_batches, run_once


def test_report_retention_removes_only_expired_drift_artifacts(tmp_path):
    old = tmp_path / "drift-old.json"
    keep = tmp_path / "unrelated.json"
    old.write_text("{}", encoding="utf-8")
    keep.write_text("{}", encoding="utf-8")
    timestamp = (datetime.now(UTC) - timedelta(days=10)).timestamp()
    import os

    os.utime(old, (timestamp, timestamp))
    assert clean_report_files(str(tmp_path), 7) == 1
    assert not old.exists()
    assert keep.exists()


class Result:
    def __init__(self, count):
        self.rowcount = count


class Connection:
    def __init__(self):
        self.counts = iter([5000, 2])
        self.commits = 0

    def execute(self, query, values):
        assert "DELETE FROM pipeline_metrics" in query
        assert values == (90, 5000)
        return Result(next(self.counts))

    def commit(self):
        self.commits += 1


def test_database_retention_deletes_in_bounded_batches():
    connection = Connection()
    assert delete_in_batches(connection, "pipeline_metrics", "metric_time", 90) == 5002
    assert connection.commits == 2


def test_run_once_applies_all_configured_policies(monkeypatch):
    class ContextConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    calls = []
    monkeypatch.setattr("maintenance.retention.psycopg.connect", lambda _url: ContextConnection())
    monkeypatch.setattr(
        "maintenance.retention.delete_in_batches",
        lambda _connection, table, column, days: calls.append((table, column, days)) or 1,
    )
    monkeypatch.setattr("maintenance.retention.clean_report_files", lambda *_args: 2)
    result = run_once("postgresql://test")
    assert result["kafka_outbox"] == 1
    assert result["report_files"] == 2
    assert {call[0] for call in calls} >= {
        "scored_transactions",
        "rejected_transactions",
        "pipeline_metrics",
        "model_drift_reports",
        "kafka_outbox",
    }
