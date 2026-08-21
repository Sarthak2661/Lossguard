from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from lossguard.constants import CATEGORY_MARGIN_PCT


def _ltv_band(card_number: str, salt: str) -> str:
    digest = hashlib.sha256(f"{salt}:{card_number}".encode()).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return "low" if bucket < 50 else "medium" if bucket < 85 else "high"


def load_training_data(path: str, max_rows: int | None, salt: str) -> pd.DataFrame:
    usecols = [
        "trans_date_trans_time",
        "cc_num",
        "category",
        "amt",
        "city_pop",
        "dob",
        "lat",
        "long",
        "merch_lat",
        "merch_long",
        "is_fraud",
    ]
    frame = pd.read_csv(path, usecols=usecols, nrows=max_rows, dtype={"cc_num": "string"})
    event_time = pd.to_datetime(frame["trans_date_trans_time"], errors="raise")
    dob = pd.to_datetime(frame["dob"], errors="raise")
    lat1, lat2 = np.radians(frame["lat"]), np.radians(frame["merch_lat"])
    delta_lat = lat2 - lat1
    delta_long = np.radians(frame["merch_long"] - frame["long"])
    haversine = (
        np.sin(delta_lat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(delta_long / 2) ** 2
    ).clip(0, 1)

    result = pd.DataFrame(
        {
            "event_time": event_time,
            "amount": frame["amt"].astype(float),
            "log_amount": np.log1p(frame["amt"].astype(float)),
            "distance_km": 6371.0088 * 2 * np.arctan2(np.sqrt(haversine), np.sqrt(1 - haversine)),
            "transaction_hour": event_time.dt.hour,
            "transaction_day_of_week": event_time.dt.dayofweek,
            "customer_age": (
                event_time.dt.year
                - dob.dt.year
                - (
                    (event_time.dt.month < dob.dt.month)
                    | ((event_time.dt.month == dob.dt.month) & (event_time.dt.day < dob.dt.day))
                ).astype(int)
            ),
            "city_population": frame["city_pop"].astype(int),
            "is_night": ((event_time.dt.hour < 6) | (event_time.dt.hour >= 22)).astype(int),
            "merchant_category": frame["category"],
            "channel": np.where(
                frame["category"].str.endswith("_net") | frame["category"].eq("travel"),
                "card_not_present",
                "card_present",
            ),
            "order_margin_pct": frame["category"].map(CATEGORY_MARGIN_PCT).astype(float),
            "customer_ltv_band": frame["cc_num"].map(lambda value: _ltv_band(str(value), salt)),
            "is_fraud": frame["is_fraud"].astype(int),
        }
    )
    return result.sort_values("event_time").reset_index(drop=True)
