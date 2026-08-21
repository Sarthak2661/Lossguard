from __future__ import annotations

import json
from datetime import date

import pandas as pd
from sqlalchemy import Engine, create_engine, text

from lossguard.explanations import LLMProviderConfig, explain_transaction


def sqlalchemy_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def create_db_engine(database_url: str) -> Engine:
    return create_engine(
        sqlalchemy_url(database_url),
        pool_pre_ping=True,
        pool_size=3,
        connect_args={"connect_timeout": 5},
    )


def available_window(engine: Engine) -> tuple[date, date, str]:
    query = text(
        """
        select min(metric_date) as min_date, max(metric_date) as max_date,
               max(source_freshness)::text as freshness
        from analytics_marts.mart_daily_segment_kpis
        """
    )
    with engine.connect() as connection:
        row = connection.execute(query).mappings().one()
    if row["min_date"] is None:
        raise ValueError("No scored transactions are available yet")
    return row["min_date"], row["max_date"], row["freshness"]


def load_latest_model_health(engine: Engine) -> dict | None:
    query = text(
        """
        select generated_at, model_version, reference_rows, current_rows,
               drifted_features, total_features, drift_share, drift_threshold,
               health_status, current_window_start, current_window_end,
               report_html_path, details
        from public.model_drift_reports
        order by generated_at desc
        limit 1
        """
    )
    with engine.connect() as connection:
        row = connection.execute(query).mappings().first()
    return dict(row) if row else None


def load_daily_kpis(engine: Engine, start_date: date, end_date: date) -> pd.DataFrame:
    query = text(
        """
        select *
        from analytics_marts.mart_daily_segment_kpis
        where metric_date between :start_date and :end_date
        order by metric_date, merchant_category
        """
    )
    return pd.read_sql(query, engine, params={"start_date": start_date, "end_date": end_date})


def load_simulation_rows(
    engine: Engine, start_date: date, end_date: date, category: str, limit: int = 50_000
) -> pd.DataFrame:
    query = text(
        """
        select transaction_id, amount::double precision as amount,
               order_margin_pct::double precision as order_margin_pct,
               customer_ltv_band, fraud_label,
               fraud_probability::double precision as fraud_probability,
               realized_policy_cost::double precision as current_policy_cost
        from public.scored_transactions
        where event_time::date between :start_date and :end_date
          and merchant_category = :category
          and fraud_label is not null
        order by event_time desc
        limit :row_limit
        """
    )
    return pd.read_sql(
        query,
        engine,
        params={
            "start_date": start_date,
            "end_date": end_date,
            "category": category,
            "row_limit": limit,
        },
    )


def load_recent_transactions(engine: Engine, category: str, limit: int = 200) -> pd.DataFrame:
    query = text(
        """
        select transaction_id, event_time, merchant, merchant_category, amount,
               fraud_probability, decision, model_version, explanation, feature_snapshot,
               explanation_text, explanation_source, explanation_model,
               explanation_generated_at
        from public.scored_transactions
        where merchant_category = :category
        order by event_time desc
        limit :row_limit
        """
    )
    frame = pd.read_sql(query, engine, params={"category": category, "row_limit": limit})
    for column in ("explanation", "feature_snapshot"):
        frame[column] = frame[column].map(
            lambda value: json.loads(value) if isinstance(value, str) else value
        )
    return frame


def get_or_create_plain_explanation(
    engine: Engine,
    transaction: dict,
    *,
    provider_config: LLMProviderConfig,
    force: bool = False,
) -> dict:
    """Generate once on review and persist the result so dashboard reruns are free."""
    transaction_id = str(transaction["transaction_id"])
    with engine.begin() as connection:
        connection.execute(
            text("select pg_advisory_xact_lock(hashtextextended(:transaction_id, 0))"),
            {"transaction_id": transaction_id},
        )
        cached = (
            connection.execute(
                text(
                    """
                select explanation_text, explanation_source, explanation_model,
                       explanation_generated_at
                from public.scored_transactions
                where transaction_id = :transaction_id
                """
                ),
                {"transaction_id": transaction_id},
            )
            .mappings()
            .one()
        )
        cached_can_be_used = cached["explanation_text"] and (
            cached["explanation_source"] != "template"
            or provider_config.provider == "template"
            or cached["explanation_model"] == provider_config.model
        )
        if cached_can_be_used and not force:
            return dict(cached)

        result = explain_transaction(
            transaction,
            transaction.get("explanation") or [],
            transaction.get("feature_snapshot") or {},
            provider_config=provider_config,
        )
        saved = (
            connection.execute(
                text(
                    """
                update public.scored_transactions
                set explanation_text = :explanation_text,
                    explanation_source = :explanation_source,
                    explanation_model = :explanation_model,
                    explanation_generated_at = now()
                where transaction_id = :transaction_id
                returning explanation_text, explanation_source, explanation_model,
                          explanation_generated_at
                """
                ),
                {
                    "transaction_id": transaction_id,
                    "explanation_text": result.text,
                    "explanation_source": result.source,
                    "explanation_model": result.model,
                },
            )
            .mappings()
            .one()
        )
    return dict(saved)
