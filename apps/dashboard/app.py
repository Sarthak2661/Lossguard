from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from apps.dashboard.data import (
    available_window,
    create_db_engine,
    get_or_create_plain_explanation,
    load_daily_kpis,
    load_latest_model_health,
    load_recent_transactions,
    load_simulation_rows,
)
from apps.dashboard.simulation import simulate_threshold
from lossguard.config import get_settings
from lossguard.explanations import resolve_llm_provider

st.set_page_config(page_title="LossGuard", page_icon="🛡️", layout="wide")
st.title("LossGuard — Fraud vs. Friction")
st.caption(
    "Retrospective simulation on labelled Sparkov data. Dollar values are modeled estimates, "
    "not realized merchant savings."
)


@st.cache_resource
def database_engine(database_url: str):
    return create_db_engine(database_url)


settings = get_settings()
llm_provider = resolve_llm_provider(
    provider=settings.llm_provider,
    anthropic_api_key=settings.anthropic_api_key,
    anthropic_model=settings.anthropic_model,
    openai_api_key=settings.openai_api_key,
    openai_model=settings.openai_model,
    gemini_api_key=settings.gemini_api_key,
    gemini_model=settings.gemini_model,
    openai_compatible_base_url=settings.openai_compatible_base_url,
    openai_compatible_api_key=settings.openai_compatible_api_key,
    openai_compatible_model=settings.openai_compatible_model,
    timeout_seconds=settings.llm_explanation_timeout_seconds,
)


@st.cache_data(ttl=30)
def cached_window():
    return available_window(database_engine(settings.database_url))


@st.cache_data(ttl=30)
def cached_kpis(start_date, end_date):
    return load_daily_kpis(database_engine(settings.database_url), start_date, end_date)


@st.cache_data(ttl=30)
def cached_simulation(start_date, end_date, category):
    return load_simulation_rows(
        database_engine(settings.database_url), start_date, end_date, category
    )


@st.cache_data(ttl=30)
def cached_transactions(category):
    return load_recent_transactions(database_engine(settings.database_url), category)


@st.cache_data(ttl=30)
def cached_model_health():
    return load_latest_model_health(database_engine(settings.database_url))


try:
    min_date, max_date, freshness = cached_window()
except Exception as exc:
    st.error(
        "LossGuard could not read the analytics database. For a local dashboard, start PostgreSQL "
        "with `docker compose up -d postgres`, then run the dbt models if needed. Expected host "
        "connection: `localhost:55432`. Database detail: " + str(exc)
    )
    st.stop()

try:
    model_health = cached_model_health()
except Exception:
    model_health = None

if model_health is None:
    st.info("Model health: not evaluated yet. The scheduled Evidently job will publish a status.")
elif model_health["health_status"] == "ok":
    st.success(
        "Model health: OK · "
        f"{model_health['drifted_features']}/{model_health['total_features']} features drifting "
        f"({float(model_health['drift_share']):.0%}) · checked {model_health['generated_at']}"
    )
elif model_health["health_status"] == "drifting":
    st.warning(
        "Model health: DRIFTING · "
        f"{model_health['drifted_features']}/{model_health['total_features']} features drifting "
        f"({float(model_health['drift_share']):.0%}) · checked {model_health['generated_at']}"
    )
else:
    st.info(
        f"Model health: {model_health['health_status'].replace('_', ' ').upper()} · "
        f"checked {model_health['generated_at']}"
    )

default_start = max(min_date, max_date - timedelta(days=29))
with st.sidebar:
    st.header("Analysis window")
    chosen_dates = st.date_input(
        "Transaction dates", value=(default_start, max_date), min_value=min_date, max_value=max_date
    )
    if not isinstance(chosen_dates, tuple) or len(chosen_dates) != 2:
        st.info("Choose a start and end date.")
        st.stop()
    start_date, end_date = chosen_dates

daily = cached_kpis(start_date, end_date)
all_categories = sorted(daily["merchant_category"].unique().tolist())
with st.sidebar:
    categories = st.multiselect("Merchant categories", all_categories, default=all_categories)
    st.caption(f"Source refreshed: {freshness}")
if not categories:
    st.warning("Select at least one merchant category.")
    st.stop()
daily = daily[daily["merchant_category"].isin(categories)].copy()

totals = daily.select_dtypes("number").sum()
fraud_rate = totals["fraud_transaction_count"] / max(totals["transaction_count"], 1)
intervention_rate = totals["fraud_intervened_count"] / max(totals["fraud_transaction_count"], 1)
false_decline_rate = totals["false_decline_count"] / max(
    totals["transaction_count"] - totals["fraud_transaction_count"], 1
)

cards = st.columns(5)
cards[0].metric("Transactions", f"{totals['transaction_count']:,.0f}")
cards[1].metric("Estimated savings", f"${totals['estimated_savings']:,.0f}")
cards[2].metric("Fraud rate", f"{fraud_rate:.2%}")
cards[3].metric("Fraud intervened", f"{intervention_rate:.1%}")
cards[4].metric("False-decline rate", f"{false_decline_rate:.2%}")

st.subheader("Decision outcomes in dollars")
outcome_cards = st.columns(4)
outcome_cards[0].metric("Fraud caught", f"${totals['fraud_caught_value']:,.0f}")
outcome_cards[1].metric("Friction cost", f"${totals['friction_cost']:,.0f}")
outcome_cards[2].metric("Fraud missed", f"${totals['fraud_missed_cost']:,.0f}")
outcome_cards[3].metric("Normal approvals", f"${totals['normal_approval_value']:,.0f}")
st.caption(
    "Fraud caught is modeled prevented fraud exposure; friction includes verification operations "
    "and legitimate-customer loss; normal approvals are legitimate approved transaction volume."
)

st.subheader("Cost and decision movement")
daily_total = (
    daily.groupby("metric_date", as_index=False)[
        ["policy_cost", "baseline_cost", "approved_count", "verified_count", "declined_count"]
    ]
    .sum()
    .sort_values("metric_date")
)
cost_long = daily_total.melt(
    id_vars="metric_date",
    value_vars=["policy_cost", "baseline_cost"],
    var_name="cost_type",
    value_name="cost",
)
left, right = st.columns(2)
with left:
    st.plotly_chart(
        px.line(cost_long, x="metric_date", y="cost", color="cost_type", markers=True),
        width="stretch",
    )
with right:
    decision_long = daily_total.melt(
        id_vars="metric_date",
        value_vars=["approved_count", "verified_count", "declined_count"],
        var_name="decision",
        value_name="transactions",
    )
    st.plotly_chart(
        px.area(decision_long, x="metric_date", y="transactions", color="decision"),
        width="stretch",
    )

st.subheader("Segment performance")
segment = daily.groupby("merchant_category", as_index=False)[
    [
        "transaction_count",
        "fraud_transaction_count",
        "fraud_intervened_count",
        "false_decline_count",
        "policy_cost",
        "baseline_cost",
        "estimated_savings",
    ]
].sum()
segment["fraud_intervention_rate"] = segment["fraud_intervened_count"] / segment[
    "fraud_transaction_count"
].clip(lower=1)
segment["false_decline_rate"] = segment["false_decline_count"] / (
    segment["transaction_count"] - segment["fraud_transaction_count"]
).clip(lower=1)
st.plotly_chart(
    px.bar(
        segment.sort_values("estimated_savings"),
        x="estimated_savings",
        y="merchant_category",
        orientation="h",
        color="false_decline_rate",
        labels={"estimated_savings": "Estimated savings ($)"},
    ),
    width="stretch",
)
st.dataframe(
    segment.sort_values("estimated_savings", ascending=False),
    width="stretch",
    hide_index=True,
    column_config={
        "fraud_intervention_rate": st.column_config.NumberColumn(format="%.1%%"),
        "false_decline_rate": st.column_config.NumberColumn(format="%.2%%"),
        "policy_cost": st.column_config.NumberColumn(format="$%.2f"),
        "baseline_cost": st.column_config.NumberColumn(format="$%.2f"),
        "estimated_savings": st.column_config.NumberColumn(format="$%.2f"),
    },
)

st.subheader("What if we move the decline threshold?")
simulation_category = st.selectbox("Segment", categories, key="simulation_category")
simulation_rows = cached_simulation(start_date, end_date, simulation_category)
if simulation_rows.empty:
    st.info("No labelled transactions are available for this segment and date window.")
else:
    decline_threshold = st.slider(
        "Decline threshold", min_value=0.05, max_value=0.95, value=0.50, step=0.01
    )
    result = simulate_threshold(simulation_rows, decline_threshold)
    sim_cards = st.columns(5)
    sim_cards[0].metric("Simulated total cost", f"${result['total_cost']:,.0f}")
    sim_cards[1].metric("Verify threshold", f"{result['verify_threshold']:.2f}")
    sim_cards[2].metric("Approved", f"{result['approve_count']:,}")
    sim_cards[3].metric("Verified", f"{result['verify_count']:,}")
    sim_cards[4].metric("Declined", f"{result['decline_count']:,}")

    st.markdown("**Dollar outcome at this threshold**")
    threshold_outcome_cards = st.columns(4)
    threshold_outcome_cards[0].metric("Fraud caught", f"${result['fraud_caught_value']:,.0f}")
    threshold_outcome_cards[1].metric("Friction cost", f"${result['friction_cost']:,.0f}")
    threshold_outcome_cards[2].metric("Fraud missed", f"${result['fraud_missed_cost']:,.0f}")
    threshold_outcome_cards[3].metric(
        "Normal approvals", f"${result['normal_approval_value']:,.0f}"
    )
    threshold_outcomes = pd.DataFrame(
        {
            "Outcome": ["Fraud caught", "Friction cost", "Fraud missed", "Normal approvals"],
            "Dollars": [
                result["fraud_caught_value"],
                result["friction_cost"],
                result["fraud_missed_cost"],
                result["normal_approval_value"],
            ],
        }
    )
    st.plotly_chart(
        px.bar(
            threshold_outcomes,
            x="Outcome",
            y="Dollars",
            color="Outcome",
            text_auto="$.2s",
            labels={"Dollars": "Amount ($)"},
        ),
        width="stretch",
    )
    grid = pd.DataFrame(
        [
            {"decline_threshold": value, **simulate_threshold(simulation_rows, float(value))}
            for value in [round(x / 100, 2) for x in range(5, 96, 5)]
        ]
    )
    threshold_chart = px.line(
        grid, x="decline_threshold", y="total_cost", markers=True, labels={"total_cost": "Cost ($)"}
    )
    threshold_chart.add_vline(x=decline_threshold, line_dash="dash")
    st.plotly_chart(threshold_chart, width="stretch")

st.subheader("Why was this transaction flagged?")
detail_category = st.selectbox("Transaction category", categories, key="detail_category")
recent = cached_transactions(detail_category)
if recent.empty:
    st.info("No transactions are available for this category.")
else:
    transaction_id = st.selectbox("Transaction", recent["transaction_id"].tolist())
    selected = recent.loc[recent["transaction_id"] == transaction_id].iloc[0]
    st.write(
        f"**{selected['decision'].upper()}** · risk {float(selected['fraud_probability']):.2%} · "
        f"${float(selected['amount']):,.2f} · {selected['merchant']} · "
        f"model {selected['model_version']}"
    )
    selected_record = selected.to_dict()
    try:
        plain_explanation = get_or_create_plain_explanation(
            database_engine(settings.database_url),
            selected_record,
            provider_config=llm_provider,
        )
        with st.container(border=True):
            st.markdown(f"**{plain_explanation['explanation_text']}**")
            provider_labels = {
                "claude": "Anthropic Claude",
                "anthropic": "Anthropic Claude",
                "openai": "OpenAI",
                "gemini": "Google Gemini",
                "openai_compatible": "an OpenAI-compatible provider",
            }
            source = plain_explanation["explanation_source"]
            if source in provider_labels:
                st.caption(
                    f"Plain-English explanation generated by {provider_labels[source]} using "
                    f"{plain_explanation['explanation_model']} and cached in PostgreSQL."
                )
            else:
                st.caption(
                    "Local fallback explanation, cached in PostgreSQL. Configure `LLM_PROVIDER` "
                    "and the selected provider's private API settings to enable LLM wording."
                )
    except Exception as exc:
        st.warning(f"The plain-English explanation cache is unavailable: {exc}")

    explanation = pd.DataFrame(selected["explanation"] or [])
    if explanation.empty:
        st.info("No feature explanation was recorded for this transaction.")
    else:
        st.caption("Technical detail: raw SHAP feature contributions")
        explanation = explanation.sort_values("contribution")
        st.plotly_chart(
            px.bar(
                explanation,
                x="contribution",
                y="feature",
                orientation="h",
                color="contribution",
                color_continuous_scale="RdBu_r",
                color_continuous_midpoint=0,
            ),
            width="stretch",
        )

with st.expander("Metric definitions and caveats"):
    st.markdown(
        """
        - **Estimated savings:** baseline simulated decision cost minus category-policy
          simulated cost.
        - **Fraud caught:** fraud amount declined plus 85% of fraud sent to verification.
        - **Friction cost:** verification operating cost plus modeled legitimate-customer
          abandonment or false-decline loss.
        - **Fraud missed:** fraud loss remaining after approvals and verification.
        - **Normal approvals:** legitimate approved transaction volume, not profit or savings.
        - **Fraud intervened:** labelled fraud receiving verify or decline; verification
          effectiveness is assumed.
        - **False decline:** labelled legitimate transaction receiving decline.
        - The source is a public synthetic fraud dataset. Cost parameters and LTV bands are
          documented assumptions.
        - The selected date is source event time; freshness is the latest pipeline processing
          timestamp.
        - **Model health:** Evidently compares recently processed feature snapshots with a
          deterministic sample of the model-training data; `DRIFTING` means the configured share
          of features crossed their statistical drift tests, not that fraud accuracy has failed.
        - **Plain-English explanation:** generated lazily from allowlisted transaction fields and
          top SHAP drivers, then cached. It summarizes model evidence and is not proof of fraud.
        """
    )
