import pandas as pd
import pytest

from apps.dashboard.simulation import simulate_threshold


def test_threshold_simulation_reconciles_decisions():
    frame = pd.DataFrame(
        {
            "fraud_probability": [0.01, 0.2, 0.9],
            "fraud_label": [False, False, True],
            "amount": [20.0, 40.0, 500.0],
            "order_margin_pct": [0.2, 0.2, 0.2],
            "customer_ltv_band": ["low", "medium", "high"],
        }
    )
    result = simulate_threshold(frame, 0.5)
    assert result["approve_count"] + result["verify_count"] + result["decline_count"] == 3
    assert result["fraud_intervened"] == 1
    assert result["total_cost"] >= 0
    assert result["total_cost"] == pytest.approx(
        result["fraud_missed_cost"] + result["friction_cost"]
    )


def test_threshold_changes_the_dollar_outcome_breakdown():
    frame = pd.DataFrame(
        {
            "fraud_probability": [0.01, 0.2, 0.9],
            "fraud_label": [False, False, True],
            "amount": [20.0, 40.0, 500.0],
            "order_margin_pct": [0.2, 0.2, 0.2],
            "customer_ltv_band": ["low", "medium", "high"],
        }
    )
    lower = simulate_threshold(frame, 0.50)
    higher = simulate_threshold(frame, 0.95)

    assert lower["fraud_caught_value"] != higher["fraud_caught_value"]
    assert lower["fraud_missed_cost"] != higher["fraud_missed_cost"]
