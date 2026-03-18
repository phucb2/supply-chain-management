"""Shipment endpoints — get, tracking, status update."""

from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import get_shipment, get_shipment_tracking_events
from app.db.session import get_session
from app.kafka.producer import publish_event
from app.models.schemas import ShipmentResponse, TrackingEvent

logger = structlog.get_logger()

router = APIRouter()


@router.get("/{shipment_id}", response_model=ShipmentResponse)
async def get_shipment_endpoint(shipment_id: UUID, session: AsyncSession = Depends(get_session)):
    """Retrieve shipment details and current status."""
    shipment = await get_shipment(session, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment


@router.get("/{shipment_id}/tracking")
async def get_tracking(shipment_id: UUID, session: AsyncSession = Depends(get_session)):
    """Get real-time tracking events for a shipment."""
    shipment = await get_shipment(session, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    events = await get_shipment_tracking_events(session, shipment_id)
    return [
        {
            "event_type": e.event_type,
            "payload": e.payload,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]


@router.post("/{shipment_id}/status", status_code=202)
async def update_status(
    shipment_id: UUID,
    body: TrackingEvent,
    session: AsyncSession = Depends(get_session),
):
    """Driver/warehouse pushes a tracking status update."""
    shipment = await get_shipment(session, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    publish_event(
        topic="shipment.status-updated",
        key=str(shipment_id),
        value={
            "shipment_id": str(shipment_id),
            "order_id": str(shipment.order_id),
            "status": body.status.value,
            "location": body.location,
            "timestamp": (body.timestamp or datetime.now(timezone.utc)).isoformat(),
        },
    )

    return {"detail": "Accepted"}
