from __future__ import annotations

import argparse
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import psycopg

from lossguard.features import MODEL_CATEGORICAL_FEATURES, MODEL_FEATURES
from ml.data import load_training_data

LOGGER = logging.getLogger("lossguard.drift")


@dataclass(frozen=True)
class DriftConfig:
    database_url: str
    training_path: str
    report_dir: str
    reference_rows: int
    current_rows: int
    min_current_rows: int
    drift_share_threshold: float
    model_metadata_path: str
    pii_hash_salt: str

    @classmethod
    def from_env(cls) -> DriftConfig:
        return cls(
            database_url=os.environ["DATABASE_URL"],
            training_path=os.getenv("DRIFT_TRAINING_PATH", "dataset/fraudTrain.csv"),
            report_dir=os.getenv("DRIFT_REPORT_DIR", "reports/drift"),
            reference_rows=int(os.getenv("DRIFT_REFERENCE_ROWS", "10000")),
            current_rows=int(os.getenv("DRIFT_CURRENT_ROWS", "10000")),
            min_current_rows=int(os.getenv("DRIFT_MIN_CURRENT_ROWS", "500")),
            drift_share_threshold=float(os.getenv("DRIFT_SHARE_THRESHOLD", "0.30")),
            model_metadata_path=os.getenv("MODEL_METADATA_PATH", "models/model_metadata.json"),
            pii_hash_salt=os.environ["PII_HASH_SALT"],
        )


def model_version(metadata_path: str) -> str:
    path = Path(metadata_path)
    if not path.exists():
        return "unknown"
    return str(json.loads(path.read_text(encoding="utf-8")).get("model_version", "unknown"))


def load_reference(config: DriftConfig) -> pd.DataFrame:
    frame = load_training_data(
        config.training_path,
        max_rows=config.reference_rows,
        salt=config.pii_hash_salt,
    )
    return frame[MODEL_FEATURES].copy()


def load_current(config: DriftConfig) -> tuple[pd.DataFrame, datetime | None, datetime | None]:
    query = """
        select feature_snapshot, processed_at
        from scored_transactions
        where feature_snapshot <> '{}'::jsonb
        order by processed_at desc
        limit %s
    """
    with psycopg.connect(config.database_url) as connection:
        rows = connection.execute(query, (config.current_rows,)).fetchall()
    snapshots = [row[0] for row in rows]
    frame = pd.DataFrame(snapshots)
    for feature in MODEL_FEATURES:
        if feature not in frame:
            frame[feature] = None
    if not frame.empty:
        for feature in MODEL_CATEGORICAL_FEATURES:
            frame[feature] = frame[feature].astype("string")
    timestamps = [row[1] for row in rows]
    return (
        frame[MODEL_FEATURES],
        min(timestamps) if timestamps else None,
        max(timestamps) if timestamps else None,
    )


def simulate_distribution_shift(frame: pd.DataFrame) -> pd.DataFrame:
    """Create an in-memory feature shift for a drift-monitoring smoke test."""
    shifted = frame.copy()
    if "amount" in shifted:
        shifted["amount"] = shifted["amount"].astype(float) * 25 + 1000
        shifted["log_amount"] = shifted["amount"].map(math.log1p)
    if "distance_km" in shifted:
        shifted["distance_km"] = shifted["distance_km"].astype(float) + 5000
    if "transaction_hour" in shifted:
        shifted["transaction_hour"] = (shifted["transaction_hour"].astype(float) + 12) % 24
    if "city_population" in shifted:
        shifted["city_population"] = shifted["city_population"].astype(float) * 50 + 1_000_000
    shifted["merchant_category"] = "shifted_demo_category"
    shifted["channel"] = "shifted_demo_channel"
    shifted["customer_ltv_band"] = "shifted_demo_band"
    return shifted


def drift_summary(snapshot_json: dict, total_features: int) -> tuple[int, int, float]:
    for metric in snapshot_json.get("metrics", []):
        config_type = metric.get("config", {}).get("type", "")
        if config_type.endswith("DriftedColumnsCount"):
            value = metric.get("value", {})
            count = int(round(float(value.get("count", 0))))
            share = float(value.get("share", 0.0))
            return count, total_features, share
    raise ValueError("Evidently report did not contain DriftedColumnsCount")


def health_status(drift_share: float, threshold: float) -> str:
    return "drifting" if drift_share >= threshold else "ok"


def persist_result(
    config: DriftConfig,
    *,
    version: str,
    reference_rows: int,
    current_rows: int,
    drifted_features: int,
    total_features: int,
    drift_share: float,
    status: str,
    window_start: datetime | None,
    window_end: datetime | None,
    json_path: str | None,
    html_path: str | None,
    details: dict,
) -> None:
    with psycopg.connect(config.database_url) as connection:
        connection.execute(
            """
            insert into model_drift_reports (
                model_version, reference_rows, current_rows, drifted_features,
                total_features, drift_share, drift_threshold, health_status,
                current_window_start, current_window_end, report_json_path,
                report_html_path, details
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                version,
                reference_rows,
                current_rows,
                drifted_features,
                total_features,
                drift_share,
                config.drift_share_threshold,
                status,
                window_start,
                window_end,
                json_path,
                html_path,
                json.dumps(details),
            ),
        )


def _run_report(config: DriftConfig, simulate_shift: bool = False) -> dict:
    from evidently import Report
    from evidently.presets import DataDriftPreset

    reference = load_reference(config)
    current, window_start, window_end = load_current(config)
    version = model_version(config.model_metadata_path)
    if len(current) < config.min_current_rows:
        result = {
            "status": "insufficient_data",
            "reference_rows": len(reference),
            "current_rows": len(current),
            "drifted_features": 0,
            "total_features": len(MODEL_FEATURES),
            "drift_share": 0.0,
        }
        persist_result(
            config,
            version=version,
            reference_rows=len(reference),
            current_rows=len(current),
            drifted_features=0,
            total_features=len(MODEL_FEATURES),
            drift_share=0.0,
            status="insufficient_data",
            window_start=window_start,
            window_end=window_end,
            json_path=None,
            html_path=None,
            details={"reason": f"requires at least {config.min_current_rows} current rows"},
        )
        return result

    if simulate_shift:
        current = simulate_distribution_shift(current)
    snapshot = Report([DataDriftPreset()]).run(current, reference)
    snapshot_json = json.loads(snapshot.json())
    drifted, total, share = drift_summary(snapshot_json, len(MODEL_FEATURES))
    status = health_status(share, config.drift_share_threshold)

    report_dir = Path(config.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    suffix = "-simulated-shift" if simulate_shift else ""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = report_dir / f"drift-{timestamp}{suffix}.json"
    html_path = report_dir / f"drift-{timestamp}{suffix}.html"
    snapshot.save_json(str(json_path))
    snapshot.save_html(str(html_path))

    details = {
        "simulated_shift": simulate_shift,
        "features": MODEL_FEATURES,
        "evidently_version": "0.7.21",
    }
    persist_result(
        config,
        version=version,
        reference_rows=len(reference),
        current_rows=len(current),
        drifted_features=drifted,
        total_features=total,
        drift_share=share,
        status=status,
        window_start=window_start,
        window_end=window_end,
        json_path=str(json_path),
        html_path=str(html_path),
        details=details,
    )
    result = {
        "status": status,
        "reference_rows": len(reference),
        "current_rows": len(current),
        "drifted_features": drifted,
        "total_features": total,
        "drift_share": share,
        "report_json": str(json_path),
        "report_html": str(html_path),
        "simulated_shift": simulate_shift,
    }
    LOGGER.info("Drift report: %s", result)
    return result


def run(config: DriftConfig, simulate_shift: bool = False) -> dict:
    """Run a report and persist a sanitized error state before propagating failures."""
    try:
        return _run_report(config, simulate_shift=simulate_shift)
    except Exception as exc:
        details = {
            "error_type": type(exc).__name__,
            "message": "Drift report failed; inspect drift-monitor logs",
            "simulated_shift": simulate_shift,
        }
        try:
            persist_result(
                config,
                version=model_version(config.model_metadata_path),
                reference_rows=0,
                current_rows=0,
                drifted_features=0,
                total_features=len(MODEL_FEATURES),
                drift_share=0.0,
                status="error",
                window_start=None,
                window_end=None,
                json_path=None,
                html_path=None,
                details=details,
            )
        except Exception:
            LOGGER.exception("Drift failed and its error state could not be persisted")
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a LossGuard Evidently drift report")
    parser.add_argument(
        "--simulate-shift",
        action="store_true",
        help="Shift the current frame in memory to demonstrate the health-state acceptance test",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    args = parse_args()
    print(json.dumps(run(DriftConfig.from_env(), simulate_shift=args.simulate_shift), indent=2))


if __name__ == "__main__":
    main()
