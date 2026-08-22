from __future__ import annotations

import logging
import math
from collections.abc import Callable
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from lossguard.costs import (
    action_for_probability,
    expected_action_costs,
    realized_action_cost,
)
from lossguard.features import MODEL_FEATURES, event_to_model_features
from lossguard.model_artifact import validate_bundle, verify_checksum
from lossguard.schemas import FeatureContribution, ScoreResponse, TransactionEvent

LOGGER = logging.getLogger(__name__)


class ModelService:
    def __init__(
        self,
        bundle_path: str,
        metric_recorder: Callable[[str, float, dict | None], None] | None = None,
    ):
        self.bundle_path = Path(bundle_path)
        self.bundle: dict | None = None
        self.artifact_sha256: str | None = None
        self.metric_recorder = metric_recorder
        self._explainer = None
        self.reload()

    @property
    def is_model_ready(self) -> bool:
        return self.bundle is not None

    @property
    def model_version(self) -> str:
        return self.bundle["model_version"] if self.bundle else "heuristic-v0"

    def reload(self, raise_on_error: bool = False) -> bool:
        if self.bundle_path.exists():
            try:
                digest = verify_checksum(self.bundle_path)
                candidate = validate_bundle(joblib.load(self.bundle_path))
            except Exception:
                LOGGER.exception("Model bundle validation failed for %s", self.bundle_path)
                if raise_on_error:
                    raise
                return False
            self.bundle = candidate
            self.artifact_sha256 = digest
            self._explainer = None
            LOGGER.info("Loaded verified model bundle %s (sha256=%s)", self.bundle_path, digest)
            return True
        else:
            self.bundle = None
            self.artifact_sha256 = None
            LOGGER.warning("Model bundle not found; using transparent development heuristic")
            return False

    def _record_metric(self, name: str, value: float, labels: dict | None = None) -> None:
        if self.metric_recorder is None:
            return
        try:
            self.metric_recorder(name, value, labels)
        except Exception:
            LOGGER.exception("Failed to persist scoring metric %s", name)

    def _heuristic_probability(self, features: dict) -> float:
        category_boost = {
            "shopping_net": 0.9,
            "misc_net": 0.7,
            "grocery_pos": 0.35,
            "gas_transport": 0.25,
        }.get(features["merchant_category"], 0.0)
        score = (
            -5.2
            + 0.55 * features["log_amount"]
            + 0.012 * min(features["distance_km"], 200)
            + 0.8 * features["is_night"]
            + category_boost
        )
        return 1 / (1 + math.exp(-score))

    def _predict(self, features: dict) -> tuple[float, list[FeatureContribution]]:
        if self.bundle is None:
            probability = self._heuristic_probability(features)
            contributions = [
                FeatureContribution(
                    feature="amount",
                    value=round(features["amount"], 2),
                    contribution=round(0.55 * features["log_amount"], 4),
                ),
                FeatureContribution(
                    feature="distance_km",
                    value=round(features["distance_km"], 2),
                    contribution=round(0.012 * min(features["distance_km"], 200), 4),
                ),
                FeatureContribution(
                    feature="is_night",
                    value=bool(features["is_night"]),
                    contribution=round(0.8 * features["is_night"], 4),
                ),
            ]
            return probability, contributions

        frame = pd.DataFrame([{key: features[key] for key in MODEL_FEATURES}])
        transformed = self.bundle["preprocessor"].transform(frame)
        raw_probability = float(self.bundle["model"].predict_proba(transformed)[0, 1])
        probability = float(self.bundle["calibrator"].predict([raw_probability])[0])
        probability = min(max(probability, 0.0), 1.0)
        try:
            if self._explainer is None:
                import shap

                self._explainer = shap.TreeExplainer(self.bundle["model"])
            shap_values = self._explainer.shap_values(transformed)
            if isinstance(shap_values, list):
                shap_values = shap_values[-1]
            values = np.asarray(shap_values)[0]
            top_indexes = np.argsort(np.abs(values))[-6:][::-1]
            feature_names = self.bundle["feature_names"]
            explanations = [
                FeatureContribution(
                    feature=str(feature_names[index]),
                    value=float(transformed[0, index]),
                    contribution=float(values[index]),
                )
                for index in top_indexes
            ]
        except Exception as exc:
            LOGGER.warning("SHAP explanation failed: %s", exc)
            self._record_metric(
                "shap_explanation_failures",
                1,
                {
                    "model_version": self.model_version,
                    "error_type": type(exc).__name__,
                },
            )
            explanations = []
        return probability, explanations

    def score(self, event: TransactionEvent) -> ScoreResponse:
        features = event_to_model_features(event.model_dump())
        probability, explanation = self._predict(features)
        default_thresholds = {"verify": 0.15, "decline": 0.50}
        if self.bundle:
            default_thresholds = self.bundle["global_thresholds"]
            thresholds = self.bundle["category_thresholds"].get(
                event.merchant_category, default_thresholds
            )
        else:
            thresholds = default_thresholds
        verify_threshold = float(thresholds["verify"])
        decline_threshold = float(thresholds["decline"])
        decision = action_for_probability(probability, verify_threshold, decline_threshold)
        expected = expected_action_costs(
            probability, event.amount, event.order_margin_pct, event.customer_ltv_band
        )
        realized = baseline = savings = None
        if event.fraud_label is not None:
            realized = realized_action_cost(
                decision,
                event.fraud_label,
                event.amount,
                event.order_margin_pct,
                event.customer_ltv_band,
            )
            baseline_action = action_for_probability(
                probability,
                float(default_thresholds["verify"]),
                float(default_thresholds["decline"]),
            )
            baseline = realized_action_cost(
                baseline_action,
                event.fraud_label,
                event.amount,
                event.order_margin_pct,
                event.customer_ltv_band,
            )
            savings = baseline - realized
        return ScoreResponse(
            transaction_id=event.transaction_id,
            fraud_probability=probability,
            decision=decision,
            verify_threshold=verify_threshold,
            decline_threshold=decline_threshold,
            expected_cost_approve=expected["approve"],
            expected_cost_verify=expected["verify"],
            expected_cost_decline=expected["decline"],
            realized_policy_cost=realized,
            baseline_cost=baseline,
            estimated_savings=savings,
            model_version=self.model_version,
            explanation=explanation,
            feature_snapshot=features,
        )
