import pytest
from pydantic import ValidationError

from lossguard.features import source_row_to_event
from lossguard.schemas import TransactionEvent
from tests.test_privacy_and_features import SOURCE_ROW


def test_valid_source_event_passes_schema():
    event = TransactionEvent.model_validate(source_row_to_event(SOURCE_ROW, "test-salt"))
    assert event.amount == 2.86


def test_negative_amount_is_rejected():
    payload = source_row_to_event(SOURCE_ROW, "test-salt")
    payload["amount"] = -1
    with pytest.raises(ValidationError):
        TransactionEvent.model_validate(payload)


def test_unknown_category_is_rejected():
    payload = source_row_to_event(SOURCE_ROW, "test-salt")
    payload["merchant_category"] = "unknown"
    with pytest.raises(ValidationError):
        TransactionEvent.model_validate(payload)
