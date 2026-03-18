"""Webhook dispatch — notifies external subscribers of shipment/order events."""

import hashlib
import hmac
import json
import logging

import httpx

from app.db import get_webhook_subscriptions_for_event

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10


async def dispatch_webhooks(event_type: str, payload: dict) -> None:
    """Send event payload to all active webhook subscriptions matching event_type."""
    try:
        subscriptions = await get_webhook_subscriptions_for_event(event_type)
    except Exception:
        logger.exception("Failed to query webhook subscriptions")
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
                logger.info(
                    "Webhook delivered to %s (status=%d) for event %s",
                    sub.url, resp.status_code, event_type,
                )
            except Exception:
                logger.exception("Webhook delivery failed to %s for event %s", sub.url, event_type)
