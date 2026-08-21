from __future__ import annotations

MERCHANT_CATEGORIES = {
    "entertainment",
    "food_dining",
    "gas_transport",
    "grocery_net",
    "grocery_pos",
    "health_fitness",
    "home",
    "kids_pets",
    "misc_net",
    "misc_pos",
    "personal_care",
    "shopping_net",
    "shopping_pos",
    "travel",
}

CATEGORY_MARGIN_PCT = {
    "entertainment": 0.35,
    "food_dining": 0.30,
    "gas_transport": 0.08,
    "grocery_net": 0.12,
    "grocery_pos": 0.10,
    "health_fitness": 0.38,
    "home": 0.28,
    "kids_pets": 0.32,
    "misc_net": 0.30,
    "misc_pos": 0.25,
    "personal_care": 0.35,
    "shopping_net": 0.30,
    "shopping_pos": 0.22,
    "travel": 0.18,
}

LTV_REACQUISITION_COST = {"low": 15.0, "medium": 45.0, "high": 120.0}
VERIFY_OPERATION_COST = 3.0
VERIFY_FRAUD_DETECTION_RATE = 0.85
VERIFY_LEGIT_ABANDONMENT_RATE = 0.08

RAW_TOPIC = "txns.raw"
SCORED_TOPIC = "txns.scored"
REJECTED_TOPIC = "txns.rejected"
