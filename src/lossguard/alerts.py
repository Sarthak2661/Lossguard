from __future__ import annotations

import logging

import httpx

from lossguard.schemas import ScoreResponse, TransactionEvent

LOGGER = logging.getLogger(__name__)


def is_high_risk(score: ScoreResponse, threshold: float) -> bool:
    return score.fraud_probability >= threshold


def slack_message(
    event: TransactionEvent,
    score: ScoreResponse,
    threshold: float,
    dashboard_url: str,
) -> dict:
    return {
        "text": (
            f"LossGuard high-risk transaction: {score.transaction_id} "
            f"({score.fraud_probability:.1%} risk, {score.decision.upper()})"
        ),
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*LossGuard high-risk transaction*\n"
                        f"Risk: *{score.fraud_probability:.1%}* (alert threshold {threshold:.0%})\n"
                        f"Decision: *{score.decision.upper()}*\n"
                        f"Category: `{event.merchant_category}` · Amount: `${event.amount:,.2f}`\n"
                        f"Transaction: `{score.transaction_id}`"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open LossGuard"},
                        "url": dashboard_url,
                    }
                ],
            },
        ],
    }


def send_high_risk_alert(
    event: TransactionEvent,
    score: ScoreResponse,
    webhook_url: str | None,
    threshold: float,
    dashboard_url: str,
    client: httpx.Client,
) -> bool:
    """Send an optional privacy-safe Slack alert; failures never block transaction processing."""
    if not webhook_url or not is_high_risk(score, threshold):
        return False
    try:
        response = client.post(
            webhook_url,
            json=slack_message(event, score, threshold, dashboard_url),
            timeout=5.0,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        LOGGER.warning("Slack alert failed for %s: %s", score.transaction_id, exc)
        return False
