import json

import pandas as pd

from monitoring.drift_job import (
    drift_summary,
    health_status,
    simulate_distribution_shift,
)


def test_health_status_boundary():
    assert health_status(0.29, 0.30) == "ok"
    assert health_status(0.30, 0.30) == "drifting"


def test_drift_summary_reads_evidently_metric_contract():
    payload = {
        "metrics": [
            {
                "config": {"type": "evidently:metric_v2:DriftedColumnsCount"},
                "value": {"count": 4.0, "share": 0.333333},
            }
        ]
    }
    assert drift_summary(json.loads(json.dumps(payload)), 12) == (4, 12, 0.333333)


def test_simulated_shift_materially_moves_features():
    frame = pd.DataFrame(
        {
            "amount": [10.0, 20.0],
            "log_amount": [2.4, 3.0],
            "distance_km": [2.0, 4.0],
            "transaction_hour": [1, 5],
            "city_population": [1000, 2000],
            "merchant_category": ["home", "travel"],
            "channel": ["card_present", "card_not_present"],
            "customer_ltv_band": ["low", "high"],
        }
    )
    shifted = simulate_distribution_shift(frame)
    assert shifted["amount"].min() > frame["amount"].max()
    assert shifted["distance_km"].min() > frame["distance_km"].max()
    assert shifted["merchant_category"].nunique() == 1
