from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from lossguard.constants import (
    LTV_REACQUISITION_COST,
    VERIFY_FRAUD_DETECTION_RATE,
    VERIFY_LEGIT_ABANDONMENT_RATE,
    VERIFY_OPERATION_COST,
)


def friction_cost(amount: float, margin_pct: float, ltv_band: str) -> float:
    return amount * margin_pct + LTV_REACQUISITION_COST[ltv_band]


def expected_action_costs(
    probability: float, amount: float, margin_pct: float, ltv_band: str
) -> dict[str, float]:
    friction = friction_cost(amount, margin_pct, ltv_band)
    return {
        "approve": probability * amount,
        "verify": (
            VERIFY_OPERATION_COST
            + probability * amount * (1 - VERIFY_FRAUD_DETECTION_RATE)
            + (1 - probability) * friction * VERIFY_LEGIT_ABANDONMENT_RATE
        ),
        "decline": (1 - probability) * friction,
    }


def action_for_probability(
    probability: float, verify_threshold: float, decline_threshold: float
) -> str:
    if probability >= decline_threshold:
        return "decline"
    if probability >= verify_threshold:
        return "verify"
    return "approve"


def realized_action_cost(
    action: str, is_fraud: bool, amount: float, margin_pct: float, ltv_band: str
) -> float:
    friction = friction_cost(amount, margin_pct, ltv_band)
    if action == "approve":
        return amount if is_fraud else 0.0
    if action == "verify":
        return VERIFY_OPERATION_COST + (
            amount * (1 - VERIFY_FRAUD_DETECTION_RATE)
            if is_fraud
            else friction * VERIFY_LEGIT_ABANDONMENT_RATE
        )
    if action == "decline":
        return 0.0 if is_fraud else friction
    raise ValueError(f"unknown action: {action}")


def optimize_thresholds(
    probabilities: Iterable[float],
    labels: Iterable[bool],
    amounts: Iterable[float],
    margins: Iterable[float],
    ltv_bands: Iterable[str],
) -> tuple[float, float, float]:
    probabilities = np.asarray(list(probabilities), dtype=float)
    labels = np.asarray(list(labels), dtype=bool)
    amounts = np.asarray(list(amounts), dtype=float)
    margins = np.asarray(list(margins), dtype=float)
    bands = np.asarray(list(ltv_bands), dtype=object)
    reacquisition = np.vectorize(LTV_REACQUISITION_COST.__getitem__)(bands)
    friction = amounts * margins + reacquisition

    best = (0.15, 0.50, float("inf"))
    verify_grid = np.unique(np.r_[0.01, np.linspace(0.025, 0.40, 16)])
    decline_grid = np.unique(np.r_[np.linspace(0.10, 0.90, 33), 0.95])
    for verify_threshold in verify_grid:
        for decline_threshold in decline_grid:
            if verify_threshold >= decline_threshold:
                continue
            decisions = np.where(
                probabilities >= decline_threshold,
                2,
                np.where(probabilities >= verify_threshold, 1, 0),
            )
            approve_cost = np.where(labels, amounts, 0.0)
            verify_cost = VERIFY_OPERATION_COST + np.where(
                labels,
                amounts * (1 - VERIFY_FRAUD_DETECTION_RATE),
                friction * VERIFY_LEGIT_ABANDONMENT_RATE,
            )
            decline_cost = np.where(labels, 0.0, friction)
            total = float(np.choose(decisions, [approve_cost, verify_cost, decline_cost]).sum())
            if total < best[2]:
                best = (float(verify_threshold), float(decline_threshold), total)
    return best
