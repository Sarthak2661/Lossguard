from datetime import datetime

import pytest

from lossguard.features import event_to_model_features, haversine_km, source_row_to_event
from lossguard.privacy import hash_customer_identifier, ltv_band_from_identifier

SOURCE_ROW = {
    "trans_date_trans_time": "2020-06-21 12:14:25",
    "cc_num": "2291163933867244",
    "merchant": "fraud_Kirlin and Sons",
    "category": "personal_care",
    "amt": "2.86",
    "lat": "33.9659",
    "long": "-80.9355",
    "city_pop": "333497",
    "dob": "1968-03-19",
    "trans_num": "2da90c7d74bd46a0caf3777415b3ebd3",
    "merch_lat": "33.986391",
    "merch_long": "-81.200714",
    "is_fraud": "0",
    "first": "Jeff",
    "last": "Elliott",
    "street": "351 Darlene Green",
}


def test_customer_hash_is_stable_and_salted():
    assert hash_customer_identifier("123", "salt") == hash_customer_identifier("123", "salt")
    assert hash_customer_identifier("123", "salt") != hash_customer_identifier("123", "other")
    assert len(hash_customer_identifier("123", "salt")) == 64


def test_source_conversion_drops_direct_identifiers():
    event = source_row_to_event(SOURCE_ROW, "test-salt")
    serialized = str(event)
    assert SOURCE_ROW["cc_num"] not in serialized
    assert SOURCE_ROW["first"] not in serialized
    assert SOURCE_ROW["street"] not in serialized
    assert event["merchant"] == "Kirlin and Sons"
    assert event["customer_age"] == 52


def test_ltv_band_is_supported():
    assert ltv_band_from_identifier("123", "salt") in {"low", "medium", "high"}


def test_haversine_known_distance():
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.195, rel=0.001)


def test_model_features_are_interpretable():
    event = source_row_to_event(SOURCE_ROW, "test-salt")
    features = event_to_model_features(event)
    assert features["transaction_hour"] == 12
    assert features["distance_km"] > 0
    assert features["merchant_category"] == "personal_care"
    assert datetime.fromisoformat(event["event_time"]).year == 2020
