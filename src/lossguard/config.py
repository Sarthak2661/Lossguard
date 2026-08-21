from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_db: str = "lossguard"
    postgres_user: str = "lossguard"
    postgres_password: str = "lossguard_local_only"
    database_url: str = "postgresql://lossguard:lossguard_local_only@localhost:55432/lossguard"
    kafka_bootstrap_servers: str = "localhost:19092"
    scoring_api_url: str = "http://localhost:8000"
    dataset_path: str = "dataset/fraudTest.csv"
    replay_mode: str = "demo"
    replay_limit: int = 10_000
    pii_hash_salt: str = "change-this-in-any-shared-environment"
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
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
