from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier

from lossguard.costs import optimize_thresholds
from lossguard.features import MODEL_CATEGORICAL_FEATURES, MODEL_FEATURES, MODEL_NUMERIC_FEATURES
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


def best_f1_threshold(labels: np.ndarray, probabilities: np.ndarray) -> float:
    precision, recall, thresholds = precision_recall_curve(labels, probabilities)
    if not len(thresholds):
        return 0.5
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
    return float(thresholds[int(np.nanargmax(f1))])


def train(input_path: str, output_path: str, metadata_path: str, max_rows: int | None) -> dict:
    salt = os.getenv("PII_HASH_SALT", "change-this-in-any-shared-environment")
    data = load_training_data(input_path, max_rows=max_rows, salt=salt)
    split_index = int(len(data) * 0.80)
    train_frame = data.iloc[:split_index]
    validation_frame = data.iloc[split_index:]
    if train_frame["is_fraud"].sum() == 0 or validation_frame["is_fraud"].sum() == 0:
        raise ValueError("Training and validation partitions must both contain fraud examples")

    preprocessor = build_preprocessor()
    train_matrix = preprocessor.fit_transform(train_frame[MODEL_FEATURES])
    validation_matrix = preprocessor.transform(validation_frame[MODEL_FEATURES])
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
    probabilities = model.predict_proba(validation_matrix)[:, 1]

    global_verify, global_decline, global_cost = optimize_thresholds(
        probabilities,
        validation_frame["is_fraud"],
        validation_frame["amount"],
        validation_frame["order_margin_pct"],
        validation_frame["customer_ltv_band"],
    )
    category_thresholds = {}
    for category, indexes in validation_frame.groupby("merchant_category").groups.items():
        segment = validation_frame.loc[indexes]
        segment_probabilities = probabilities[validation_frame.index.get_indexer(indexes)]
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

    model_version = f"xgb-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    feature_names = preprocessor.get_feature_names_out().tolist()
    bundle = {
        "model": model,
        "preprocessor": preprocessor,
        "feature_names": feature_names,
        "model_features": MODEL_FEATURES,
        "category_thresholds": category_thresholds,
        "global_thresholds": {"verify": global_verify, "decline": global_decline},
        "model_version": model_version,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, output)

    metadata = {
        "model_version": model_version,
        "created_at": datetime.now(UTC).isoformat(),
        "source": str(input_path),
        "rows": len(data),
        "train_rows": len(train_frame),
        "validation_rows": len(validation_frame),
        "train_fraud_rate": float(train_frame["is_fraud"].mean()),
        "validation_fraud_rate": float(validation_frame["is_fraud"].mean()),
        "roc_auc": float(roc_auc_score(validation_frame["is_fraud"], probabilities)),
        "average_precision": float(
            average_precision_score(validation_frame["is_fraud"], probabilities)
        ),
        "best_f1_threshold": best_f1_threshold(
            validation_frame["is_fraud"].to_numpy(), probabilities
        ),
        "global_thresholds": bundle["global_thresholds"],
        "global_validation_cost": round(global_cost, 2),
        "category_thresholds": category_thresholds,
        "feature_names": feature_names,
        "split_strategy": "first 80% train / last 20% validation after timestamp sort",
        "cost_model": "docs/business-assumptions.md",
    }
    metadata_output = Path(metadata_path)
    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    LOGGER.info("Saved model to %s and metadata to %s", output, metadata_output)
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the LossGuard cost-sensitive fraud model")
    parser.add_argument("--input", default="dataset/fraudTrain.csv")
    parser.add_argument("--output", default="models/fraud_model.joblib")
    parser.add_argument("--metadata-output", default="models/model_metadata.json")
    parser.add_argument("--max-rows", type=int, default=300_000)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    metadata = train(args.input, args.output, args.metadata_output, args.max_rows or None)
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
