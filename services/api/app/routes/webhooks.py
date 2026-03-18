"""Webhook endpoints — CRUD subscriptions and inbound receiver."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import create_webhook_subscription, list_webhook_subscriptions
from app.db.session import get_session
from app.kafka.producer import publish_event
from app.models.schemas import WebhookSubscription
from app.storage import upload_raw_payload

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/subscriptions", status_code=201)
async def create_subscription(
    body: WebhookSubscription,
    session: AsyncSession = Depends(get_session),
):
    """Register a webhook subscription for shipment events."""
    sub = await create_webhook_subscription(
        session, url=body.url, events=body.events, secret=body.secret,
    )
    await session.commit()
    return {"id": str(sub.id), "url": sub.url, "events": sub.events}


@router.get("/subscriptions")
async def list_subscriptions(session: AsyncSession = Depends(get_session)):
    """List active webhook subscriptions."""
    subs = await list_webhook_subscriptions(session)
    return [
        {"id": str(s.id), "url": s.url, "events": s.events, "active": bool(s.active)}
        for s in subs
    ]


@router.post("/inbound")
async def receive_webhook(request: Request, session: AsyncSession = Depends(get_session)):
    """Receive inbound webhook from carrier / channel."""
    payload = await request.json()

    event_type = payload.get("event_type", "unknown")
    reference_id = payload.get("reference_id", "unknown")

    try:
        upload_raw_payload(f"webhook-{reference_id}", payload)
    except Exception:
        logger.exception("MinIO upload failed (non-fatal)")

    topic_map = {
        "shipment.status_updated": "shipment.status-updated",
        "shipment.status-updated": "shipment.status-updated",
        "order.received": "order.received",
    }
    topic = topic_map.get(event_type)
    if topic:
        publish_event(topic=topic, key=reference_id, value=payload)

    return {"detail": "OK"}
