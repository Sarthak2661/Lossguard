from __future__ import annotations

import numpy as np
import pandas as pd

from lossguard.constants import (
    LTV_REACQUISITION_COST,
    VERIFY_FRAUD_DETECTION_RATE,
    VERIFY_LEGIT_ABANDONMENT_RATE,
    VERIFY_OPERATION_COST,
)


def simulate_threshold(frame: pd.DataFrame, decline_threshold: float) -> dict[str, float]:
    if frame.empty:
        return {
            "total_cost": 0.0,
            "approve_count": 0,
            "verify_count": 0,
            "decline_count": 0,
            "false_declines": 0,
            "fraud_intervened": 0,
            "fraud_caught_value": 0.0,
            "fraud_missed_cost": 0.0,
            "friction_cost": 0.0,
            "normal_approval_value": 0.0,
        }
    verify_threshold = max(0.01, min(decline_threshold * 0.55, decline_threshold - 0.01))
    probability = frame["fraud_probability"].to_numpy(dtype=float)
    fraud = frame["fraud_label"].to_numpy(dtype=bool)
    amount = frame["amount"].to_numpy(dtype=float)
    margin = frame["order_margin_pct"].to_numpy(dtype=float)
    reacquisition = frame["customer_ltv_band"].map(LTV_REACQUISITION_COST).to_numpy(dtype=float)
    friction = amount * margin + reacquisition
    actions = np.where(
        probability >= decline_threshold,
        "decline",
        np.where(probability >= verify_threshold, "verify", "approve"),
    )
    approve_cost = np.where(fraud, amount, 0.0)
    verify_cost = VERIFY_OPERATION_COST + np.where(
        fraud,
        amount * (1 - VERIFY_FRAUD_DETECTION_RATE),
        friction * VERIFY_LEGIT_ABANDONMENT_RATE,
    )
    decline_cost = np.where(fraud, 0.0, friction)
    total_cost = np.where(
        actions == "decline", decline_cost, np.where(actions == "verify", verify_cost, approve_cost)
    )
    fraud_caught_value = np.where(
        fraud & (actions == "decline"),
        amount,
        np.where(fraud & (actions == "verify"), amount * VERIFY_FRAUD_DETECTION_RATE, 0.0),
    )
    fraud_missed_cost = np.where(
        fraud & (actions == "approve"),
        amount,
        np.where(
            fraud & (actions == "verify"),
            amount * (1 - VERIFY_FRAUD_DETECTION_RATE),
            0.0,
        ),
    )
    friction_cost = np.where(
        actions == "verify",
        VERIFY_OPERATION_COST + np.where(~fraud, friction * VERIFY_LEGIT_ABANDONMENT_RATE, 0.0),
        np.where((actions == "decline") & ~fraud, friction, 0.0),
    )
    normal_approval_value = np.where((actions == "approve") & ~fraud, amount, 0.0)
    return {
        "verify_threshold": verify_threshold,
        "total_cost": float(total_cost.sum()),
        "approve_count": int((actions == "approve").sum()),
        "verify_count": int((actions == "verify").sum()),
        "decline_count": int((actions == "decline").sum()),
        "false_declines": int(((actions == "decline") & ~fraud).sum()),
        "fraud_intervened": int(((actions != "approve") & fraud).sum()),
        "fraud_caught_value": float(fraud_caught_value.sum()),
        "fraud_missed_cost": float(fraud_missed_cost.sum()),
        "friction_cost": float(friction_cost.sum()),
        "normal_approval_value": float(normal_approval_value.sum()),
    }
