from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

LOGGER = logging.getLogger("lossguard.retention")

POLICIES = {
    "scored_transactions": ("processed_at", "RETENTION_SCORED_DAYS", 730),
    "rejected_transactions": ("rejected_at", "RETENTION_REJECTIONS_DAYS", 30),
    "pipeline_metrics": ("metric_time", "RETENTION_METRICS_DAYS", 90),
    "model_drift_reports": ("generated_at", "RETENTION_DRIFT_REPORTS_DAYS", 180),
}


def delete_in_batches(connection, table: str, timestamp_column: str, days: int, batch=5000) -> int:
    total = 0
    while True:
        result = connection.execute(
            f"""
            DELETE FROM {table} WHERE ctid IN (
                SELECT ctid FROM {table}
                WHERE {timestamp_column} < NOW() - make_interval(days => %s)
                LIMIT %s
            )
            """,  # identifiers are fixed constants above, never user input
            (days, batch),
        )
        deleted = result.rowcount
        total += deleted
        connection.commit()
        if deleted < batch:
            return total


def clean_report_files(report_dir: str, days: int) -> int:
    root = Path(report_dir).resolve()
    if not root.exists():
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=days)
    removed = 0
    for path in root.glob("drift-*.json"):
        expired = datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff
        if path.resolve().parent == root and expired:
            path.unlink()
            removed += 1
    for path in root.glob("drift-*.html"):
        expired = datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff
        if path.resolve().parent == root and expired:
            path.unlink()
            removed += 1
    return removed


def run_once(database_url: str) -> dict[str, int]:
    deleted: dict[str, int] = {}
    with psycopg.connect(database_url) as connection:
        for table, (column, variable, default) in POLICIES.items():
            deleted[table] = delete_in_batches(
                connection, table, column, int(os.getenv(variable, str(default)))
            )
        deleted["kafka_outbox"] = delete_in_batches(
            connection,
            "kafka_outbox",
            "published_at",
            int(os.getenv("RETENTION_OUTBOX_DAYS", "7")),
        )
    deleted["report_files"] = clean_report_files(
        os.getenv("DRIFT_REPORT_DIR", "/reports/drift"),
        int(os.getenv("RETENTION_DRIFT_REPORTS_DAYS", "180")),
    )
    LOGGER.info("Retention result: %s", deleted)
    return deleted


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    interval = int(os.getenv("RETENTION_INTERVAL_SECONDS", "86400"))
    while True:
        try:
            run_once(os.environ["DATABASE_URL"])
        except psycopg.Error:
            LOGGER.exception("Retention run failed; retrying on the next interval")
        time.sleep(interval)


if __name__ == "__main__":
    main()
