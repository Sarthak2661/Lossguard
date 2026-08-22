from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from lossguard.costs import action_for_probability, optimize_thresholds, realized_action_cost
from lossguard.features import MODEL_CATEGORICAL_FEATURES, MODEL_FEATURES, MODEL_NUMERIC_FEATURES
from lossguard.model_artifact import BUNDLE_SCHEMA_VERSION, validate_bundle, write_checksum
from ml.data import load_training_data

LOGGER = logging.getLogger("lossguard.training")


def build_preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        [
            ("numeric", StandardScaler(), MODEL_NUMERIC_FEATURES),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                MODEL_CATEGORICAL_FEATURES,
            ),
        ],
        verbose_feature_names_out=False,
    )


def split_training_windows(
    data: pd.DataFrame,
    train_fraction: float = 0.70,
    calibration_fraction: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train_end = int(len(data) * train_fraction)
    calibration_end = train_end + int(len(data) * calibration_fraction)
    windows = (
        data.iloc[:train_end].copy(),
        data.iloc[train_end:calibration_end].copy(),
        data.iloc[calibration_end:].copy(),
    )
    names = ("train", "calibration", "threshold_validation")
    for name, frame in zip(names, windows, strict=True):
        if frame.empty or frame["is_fraud"].nunique() < 2:
            raise ValueError(f"{name} window must contain fraud and legitimate examples")
    return windows


def best_f1_threshold(labels: np.ndarray, probabilities: np.ndarray) -> float:
    precision, recall, thresholds = precision_recall_curve(labels, probabilities)
    if not len(thresholds):
        return 0.5
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
    return float(thresholds[int(np.nanargmax(f1))])


def probability_metrics(labels: pd.Series | np.ndarray, probabilities: np.ndarray) -> dict:
    labels_array = np.asarray(labels, dtype=int)
    clipped = np.clip(np.asarray(probabilities, dtype=float), 1e-7, 1 - 1e-7)
    return {
        "roc_auc": float(roc_auc_score(labels_array, clipped)),
        "average_precision": float(average_precision_score(labels_array, clipped)),
        "brier_score": float(brier_score_loss(labels_array, clipped)),
        "log_loss": float(log_loss(labels_array, clipped, labels=[0, 1])),
        "best_f1_threshold": best_f1_threshold(labels_array, clipped),
    }


def policy_metrics(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    global_thresholds: dict,
    category_thresholds: dict,
) -> dict:
    decisions: list[str] = []
    costs: list[float] = []
    for row, probability in zip(frame.itertuples(index=False), probabilities, strict=True):
        thresholds = category_thresholds.get(row.merchant_category, global_thresholds)
        action = action_for_probability(
            float(probability), float(thresholds["verify"]), float(thresholds["decline"])
        )
        decisions.append(action)
        costs.append(
            realized_action_cost(
                action,
                bool(row.is_fraud),
                float(row.amount),
                float(row.order_margin_pct),
                str(row.customer_ltv_band),
            )
        )
    labels = frame["is_fraud"].to_numpy(dtype=bool)
    intervened = np.asarray(decisions) != "approve"
    baseline_cost = float(frame.loc[labels, "amount"].sum())
    policy_cost = float(sum(costs))
    return {
        "policy_cost": policy_cost,
        "approve_all_baseline_cost": baseline_cost,
        "estimated_savings_vs_approve_all": baseline_cost - policy_cost,
        "fraud_intervention_rate": float(intervened[labels].mean()),
        "false_intervention_rate": float(intervened[~labels].mean()),
        "decision_counts": {
            action: decisions.count(action) for action in ("approve", "verify", "decline")
        },
    }


def window_metadata(frame: pd.DataFrame) -> dict:
    return {
        "rows": len(frame),
        "fraud_rows": int(frame["is_fraud"].sum()),
        "fraud_rate": float(frame["is_fraud"].mean()),
        "event_time_start": frame["event_time"].min().isoformat(),
        "event_time_end": frame["event_time"].max().isoformat(),
    }


def train(
    input_path: str,
    test_input_path: str,
    output_path: str,
    metadata_path: str,
    max_rows: int | None,
    max_test_rows: int | None = None,
) -> dict:
    from xgboost import XGBClassifier

    salt = os.environ["PII_HASH_SALT"]
    data = load_training_data(input_path, max_rows=max_rows, salt=salt)
    train_frame, calibration_frame, threshold_frame = split_training_windows(data)
    final_test_frame = load_training_data(test_input_path, max_rows=max_test_rows, salt=salt)
    if final_test_frame.empty or final_test_frame["is_fraud"].nunique() < 2:
        raise ValueError("final_test window must contain fraud and legitimate examples")

    preprocessor = build_preprocessor()
    train_matrix = preprocessor.fit_transform(train_frame[MODEL_FEATURES])
    calibration_matrix = preprocessor.transform(calibration_frame[MODEL_FEATURES])
    threshold_matrix = preprocessor.transform(threshold_frame[MODEL_FEATURES])
    final_test_matrix = preprocessor.transform(final_test_frame[MODEL_FEATURES])
    positive_weight = float(
        (len(train_frame) - train_frame["is_fraud"].sum()) / train_frame["is_fraud"].sum()
    )
    model = XGBClassifier(
        n_estimators=350,
        max_depth=6,
        learning_rate=0.06,
        subsample=0.85,
        colsample_bytree=0.85,
        min_child_weight=3,
        reg_lambda=2.0,
        objective="binary:logistic",
        eval_metric="aucpr",
        scale_pos_weight=positive_weight,
        n_jobs=-1,
        random_state=42,
    )
    model.fit(train_matrix, train_frame["is_fraud"])

    raw_calibration_probabilities = model.predict_proba(calibration_matrix)[:, 1]
    calibrator = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip")
    calibrator.fit(raw_calibration_probabilities, calibration_frame["is_fraud"])
    calibrated_calibration_probabilities = calibrator.predict(raw_calibration_probabilities)
    threshold_probabilities = calibrator.predict(model.predict_proba(threshold_matrix)[:, 1])
    final_test_probabilities = calibrator.predict(model.predict_proba(final_test_matrix)[:, 1])

    global_verify, global_decline, global_cost = optimize_thresholds(
        threshold_probabilities,
        threshold_frame["is_fraud"],
        threshold_frame["amount"],
        threshold_frame["order_margin_pct"],
        threshold_frame["customer_ltv_band"],
    )
    category_thresholds = {}
    for category, indexes in threshold_frame.groupby("merchant_category").groups.items():
        segment = threshold_frame.loc[indexes]
        positions = threshold_frame.index.get_indexer(indexes)
        segment_probabilities = threshold_probabilities[positions]
        if int(segment["is_fraud"].sum()) < 5:
            category_thresholds[category] = {
                "verify": global_verify,
                "decline": global_decline,
                "validation_rows": len(segment),
                "validation_fraud_rows": int(segment["is_fraud"].sum()),
                "fallback": "global",
            }
            continue
        verify, decline, cost = optimize_thresholds(
            segment_probabilities,
            segment["is_fraud"],
            segment["amount"],
            segment["order_margin_pct"],
            segment["customer_ltv_band"],
        )
        category_thresholds[category] = {
            "verify": verify,
            "decline": decline,
            "validation_cost": round(cost, 2),
            "validation_rows": len(segment),
            "validation_fraud_rows": int(segment["is_fraud"].sum()),
        }

    model_version = f"xgb-calibrated-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    feature_names = preprocessor.get_feature_names_out().tolist()
    global_thresholds = {"verify": global_verify, "decline": global_decline}
    bundle = validate_bundle(
        {
            "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
            "model": model,
            "calibrator": calibrator,
            "calibration_method": "isotonic",
            "preprocessor": preprocessor,
            "feature_names": feature_names,
            "model_features": MODEL_FEATURES,
            "category_thresholds": category_thresholds,
            "global_thresholds": global_thresholds,
            "model_version": model_version,
        }
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, output)
    artifact_sha256 = write_checksum(output)

    metadata = {
        "model_version": model_version,
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "training_source": str(input_path),
        "final_test_source": str(test_input_path),
        "windows": {
            "train": window_metadata(train_frame),
            "calibration": window_metadata(calibration_frame),
            "threshold_validation": window_metadata(threshold_frame),
            "final_test": window_metadata(final_test_frame),
        },
        "calibration": {
            "method": "isotonic",
            "raw": probability_metrics(
                calibration_frame["is_fraud"], raw_calibration_probabilities
            ),
            "calibrated": probability_metrics(
                calibration_frame["is_fraud"], calibrated_calibration_probabilities
            ),
        },
        "threshold_validation": {
            **probability_metrics(threshold_frame["is_fraud"], threshold_probabilities),
            **policy_metrics(
                threshold_frame,
                threshold_probabilities,
                global_thresholds,
                category_thresholds,
            ),
        },
        "final_test": {
            **probability_metrics(final_test_frame["is_fraud"], final_test_probabilities),
            **policy_metrics(
                final_test_frame,
                final_test_probabilities,
                global_thresholds,
                category_thresholds,
            ),
        },
        "global_thresholds": global_thresholds,
        "global_threshold_validation_cost": round(global_cost, 2),
        "category_thresholds": category_thresholds,
        "feature_names": feature_names,
        "split_strategy": (
            "timestamp ordered: first 70% train, next 15% calibration, final 15% threshold "
            "validation; fraudTest.csv is independent final test"
        ),
        "artifact": {
            "path": str(output),
            "sha256": artifact_sha256,
            "checksum_sidecar": str(output.with_name(f"{output.name}.sha256")),
        },
        "cost_model": "docs/business-assumptions.md",
    }
    metadata_output = Path(metadata_path)
    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    LOGGER.info("Saved calibrated model to %s and metadata to %s", output, metadata_output)
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the LossGuard cost-sensitive fraud model")
    parser.add_argument("--input", default="dataset/fraudTrain.csv")
    parser.add_argument("--test-input", default="dataset/fraudTest.csv")
    parser.add_argument("--output", default="models/fraud_model.joblib")
    parser.add_argument("--metadata-output", default="models/model_metadata.json")
    parser.add_argument("--max-rows", type=int, default=300_000)
    parser.add_argument("--max-test-rows", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    metadata = train(
        args.input,
        args.test_input,
        args.output,
        args.metadata_output,
        args.max_rows or None,
        args.max_test_rows or None,
    )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
