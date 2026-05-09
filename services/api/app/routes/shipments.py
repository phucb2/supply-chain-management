"""Delivery order endpoints — read and status tracking."""

from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import get_sale_order_id_for_delivery, get_shipment, get_shipment_tracking_events
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
            "event_type": f"order.{e.status}",
            "payload": {"remarks": e.remarks},
            "created_at": e.status_timestamp.isoformat(),
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

    sale_order_id = await get_sale_order_id_for_delivery(session, shipment_id)
    if not sale_order_id:
        raise HTTPException(status_code=500, detail="No sale order linked to this delivery")

    publish_event(
        topic="shipment.status-updated",
        key=str(shipment_id),
        value={
            "delivery_order_id": str(shipment_id),
            "order_id": str(sale_order_id),
            "status": body.status,
            "location": body.location,
            "timestamp": (body.timestamp or datetime.now(timezone.utc)).isoformat(),
        },
    )

    return {"detail": "Accepted"}
