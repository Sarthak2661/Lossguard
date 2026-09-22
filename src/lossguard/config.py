from __future__ import annotations

from functools import lru_cache

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_db: str = "lossguard"
    postgres_user: str = "lossguard"
    postgres_password: str
    database_url: str
    kafka_bootstrap_servers: str = "localhost:19092"
    scoring_api_url: str = "http://localhost:8000"
    scoring_api_max_attempts: int = Field(default=3, ge=1, le=10)
    scoring_api_retry_backoff_seconds: float = Field(default=0.5, ge=0, le=30)
    postgres_pool_min_size: int = Field(default=1, ge=1, le=20)
    postgres_pool_max_size: int = Field(default=8, ge=1, le=100)
    consumer_write_batch_size: int = Field(default=100, ge=1, le=5000)
    consumer_flush_seconds: float = Field(default=1.0, ge=0.05, le=60)
    dataset_path: str = "dataset/fraudTest.csv"
    replay_mode: str = "demo"
    replay_limit: int = 10_000
    pii_hash_salt: str
    scoring_api_key: str
    admin_api_key: str
    model_bundle_path: str = "models/fraud_model.joblib"
    model_metadata_path: str = "models/model_metadata.json"
    slack_webhook_url: str | None = None
    slack_high_risk_threshold: float = 0.90
    dashboard_public_url: str = "http://localhost:8501"
    llm_provider: str = "auto"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    openai_compatible_base_url: str | None = None
    openai_compatible_api_key: str | None = None
    openai_compatible_model: str | None = None
    llm_explanation_timeout_seconds: float = 8.0
    drift_health_max_age_seconds: int = Field(default=691200, ge=60)
    log_level: str = "INFO"

    @field_validator("postgres_password", "pii_hash_salt", "scoring_api_key", "admin_api_key")
    @classmethod
    def validate_secret(cls, value: str, info: ValidationInfo) -> str:
        weak_markers = ("change-this", "local_only", "generate_with_bootstrap", "your-")
        if len(value) < 24 or any(marker in value.lower() for marker in weak_markers):
            raise ValueError(
                f"{info.field_name} must be a generated secret containing at least 24 characters"
            )
        return value

    @model_validator(mode="after")
    def validate_distinct_api_keys(self) -> Settings:
        if self.scoring_api_key == self.admin_api_key:
            raise ValueError("scoring_api_key and admin_api_key must be different")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
