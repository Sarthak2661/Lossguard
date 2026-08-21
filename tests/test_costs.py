import numpy as np

from lossguard.costs import (
    action_for_probability,
    expected_action_costs,
    friction_cost,
    optimize_thresholds,
    realized_action_cost,
)


def test_action_boundaries():
    assert action_for_probability(0.01, 0.10, 0.50) == "approve"
    assert action_for_probability(0.10, 0.10, 0.50) == "verify"
    assert action_for_probability(0.50, 0.10, 0.50) == "decline"


def test_legitimate_decline_cost_includes_margin_and_reacquisition():
    assert friction_cost(100, 0.20, "medium") == 65
    assert realized_action_cost("decline", False, 100, 0.20, "medium") == 65
    assert realized_action_cost("decline", True, 100, 0.20, "medium") == 0


def test_expected_costs_are_non_negative():
    costs = expected_action_costs(0.4, 100, 0.2, "low")
    assert set(costs) == {"approve", "verify", "decline"}
    assert all(value >= 0 for value in costs.values())


def test_optimizer_returns_ordered_thresholds():
    probabilities = np.array([0.01, 0.02, 0.08, 0.2, 0.7, 0.9])
    labels = np.array([0, 0, 0, 0, 1, 1])
    amounts = np.array([20, 30, 40, 50, 200, 300])
    margins = np.full(6, 0.25)
    bands = ["low"] * 6
    verify, decline, total = optimize_thresholds(probabilities, labels, amounts, margins, bands)
    assert 0 <= verify < decline <= 1
    assert total >= 0
