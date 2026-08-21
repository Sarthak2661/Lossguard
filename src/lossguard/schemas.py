from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lossguard.constants import MERCHANT_CATEGORIES


class TransactionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=8, max_length=64)
    event_time: datetime
    customer_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    merchant: str = Field(min_length=1, max_length=160)
    merchant_category: str
    amount: float = Field(gt=0, le=1_000_000)
    customer_lat: float = Field(ge=-90, le=90)
    customer_long: float = Field(ge=-180, le=180)
    merchant_lat: float = Field(ge=-90, le=90)
    merchant_long: float = Field(ge=-180, le=180)
    city_population: int = Field(ge=0)
    customer_age: int = Field(ge=18, le=120)
    channel: Literal["card_present", "card_not_present"]
    order_margin_pct: float = Field(gt=0, le=1)
    customer_ltv_band: Literal["low", "medium", "high"]
    fraud_label: bool | None = None

    @field_validator("merchant_category")
    @classmethod
    def category_is_supported(cls, value: str) -> str:
        if value not in MERCHANT_CATEGORIES:
            raise ValueError(f"unsupported merchant category: {value}")
        return value


class FeatureContribution(BaseModel):
    feature: str
    value: float | str | bool | None = None
    contribution: float


class ScoreResponse(BaseModel):
    transaction_id: str
    fraud_probability: float = Field(ge=0, le=1)
    decision: Literal["approve", "verify", "decline"]
    verify_threshold: float
    decline_threshold: float
    expected_cost_approve: float
    expected_cost_verify: float
    expected_cost_decline: float
    realized_policy_cost: float | None = None
    baseline_cost: float | None = None
    estimated_savings: float | None = None
    model_version: str
    explanation: list[FeatureContribution]
    feature_snapshot: dict[str, float | str | bool]


class RejectedEvent(BaseModel):
    source_topic: str
    error_type: str
    error_message: str
    transaction_id: str | None = None
    payload: dict | list | str | int | float | bool | None
