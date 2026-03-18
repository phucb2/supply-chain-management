"""Webhook dispatch — notifies external subscribers of shipment/order events."""

import hashlib
import hmac
import json

import httpx
import structlog

from app.db import get_webhook_subscriptions_for_event

logger = structlog.get_logger()

TIMEOUT_SECONDS = 10


async def dispatch_webhooks(event_type: str, payload: dict) -> None:
    """Send event payload to all active webhook subscriptions matching event_type."""
    try:
        subscriptions = await get_webhook_subscriptions_for_event(event_type)
    except Exception:
        logger.exception("webhook_subscription_query_failed")
        return

    if not subscriptions:
        return

    body = json.dumps(payload)

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        for sub in subscriptions:
            try:
                headers = {"Content-Type": "application/json"}
                if sub.secret:
                    sig = hmac.new(sub.secret.encode(), body.encode(), hashlib.sha256).hexdigest()
                    headers["X-Webhook-Signature"] = sig

                resp = await client.post(sub.url, content=body, headers=headers)
                logger.info("webhook_delivered", url=sub.url, status_code=resp.status_code, event_type=event_type)
            except Exception:
                logger.exception("webhook_delivery_failed", url=sub.url, event_type=event_type)
