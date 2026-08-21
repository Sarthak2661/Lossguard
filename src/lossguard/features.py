from __future__ import annotations

import math
from datetime import date, datetime

from lossguard.constants import CATEGORY_MARGIN_PCT
from lossguard.privacy import (
    hash_customer_identifier,
    ltv_band_from_identifier,
)

MODEL_NUMERIC_FEATURES = [
    "amount",
    "log_amount",
    "distance_km",
    "transaction_hour",
    "transaction_day_of_week",
    "customer_age",
    "city_population",
    "is_night",
    "order_margin_pct",
]
MODEL_CATEGORICAL_FEATURES = ["merchant_category", "channel", "customer_ltv_band"]
MODEL_FEATURES = MODEL_NUMERIC_FEATURES + MODEL_CATEGORICAL_FEATURES


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    value = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def age_at(dob: date, at_time: datetime) -> int:
    return at_time.year - dob.year - ((at_time.month, at_time.day) < (dob.month, dob.day))


def channel_for_category(category: str) -> str:
    is_remote = category.endswith("_net") or category == "travel"
    return "card_not_present" if is_remote else "card_present"


def source_row_to_event(row: dict[str, str], salt: str) -> dict:
    event_time = datetime.strptime(row["trans_date_trans_time"], "%Y-%m-%d %H:%M:%S")
    category = row["category"]
    raw_card = row["cc_num"]
    return {
        "transaction_id": row["trans_num"],
        "event_time": event_time.isoformat(),
        "customer_id": hash_customer_identifier(raw_card, salt),
        "merchant": row["merchant"].removeprefix("fraud_"),
        "merchant_category": category,
        "amount": float(row["amt"]),
        "customer_lat": float(row["lat"]),
        "customer_long": float(row["long"]),
        "merchant_lat": float(row["merch_lat"]),
        "merchant_long": float(row["merch_long"]),
        "city_population": int(row["city_pop"]),
        "customer_age": age_at(datetime.strptime(row["dob"], "%Y-%m-%d").date(), event_time),
        "channel": channel_for_category(category),
        "order_margin_pct": CATEGORY_MARGIN_PCT[category],
        "customer_ltv_band": ltv_band_from_identifier(raw_card, salt),
        "fraud_label": bool(int(row["is_fraud"])),
    }


def event_to_model_features(event: dict) -> dict:
    event_time = event["event_time"]
    if isinstance(event_time, str):
        event_time = datetime.fromisoformat(event_time)
    amount = float(event["amount"])
    return {
        "amount": amount,
        "log_amount": math.log1p(amount),
        "distance_km": haversine_km(
            float(event["customer_lat"]),
            float(event["customer_long"]),
            float(event["merchant_lat"]),
            float(event["merchant_long"]),
        ),
        "transaction_hour": event_time.hour,
        "transaction_day_of_week": event_time.weekday(),
        "customer_age": int(event["customer_age"]),
        "city_population": int(event["city_population"]),
        "is_night": int(event_time.hour < 6 or event_time.hour >= 22),
        "order_margin_pct": float(event["order_margin_pct"]),
        "merchant_category": event["merchant_category"],
        "channel": event["channel"],
        "customer_ltv_band": event["customer_ltv_band"],
    }
