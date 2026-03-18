"""Order endpoints — import, read, list, cancel."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import (
    create_order,
    create_order_event,
    get_order,
    list_orders,
    update_order_status,
)
from app.db.session import get_session
from app.kafka.producer import publish_event
from app.models.schemas import OrderCreate, OrderResponse, OrderStatus
from app.storage import upload_raw_payload

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/import", response_model=OrderResponse, status_code=201)
async def import_order(body: OrderCreate, session: AsyncSession = Depends(get_session)):
    """Ingest order from eCommerce/ERP channel."""
    order, created = await create_order(
        session,
        external_order_id=body.external_order_id,
        channel=body.channel,
        customer_name=body.customer_name,
        customer_email=body.customer_email,
        shipping_address=body.shipping_address,
        raw_payload=body.model_dump(mode="json"),
        items=[item.model_dump() for item in body.items],
    )

    if not created:
        raise HTTPException(status_code=409, detail="Duplicate order: external_order_id already exists")

    await create_order_event(session, order.id, "order.received", {"channel": body.channel})
    await session.commit()

    publish_event(
        topic="order.received",
        key=str(order.id),
        value={
            "order_id": str(order.id),
            "external_order_id": order.external_order_id,
            "channel": order.channel,
            "customer_name": order.customer_name,
            "shipping_address": order.shipping_address,
            "items": [item.model_dump() for item in body.items],
        },
    )

    try:
        upload_raw_payload(str(order.id), body.model_dump(mode="json"))
    except Exception:
        logger.exception("MinIO upload failed (non-fatal)")

    return order


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order_endpoint(order_id: UUID, session: AsyncSession = Depends(get_session)):
    """Retrieve order by ID."""
    order = await get_order(session, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("/", response_model=list[OrderResponse])
async def list_orders_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: OrderStatus | None = None,
    channel: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """List orders with pagination and filters."""
    return await list_orders(
        session,
        skip=skip,
        limit=limit,
        status_filter=status.value if status else None,
        channel_filter=channel,
    )


@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(order_id: UUID, session: AsyncSession = Depends(get_session)):
    """Request order cancellation."""
    order = await get_order(session, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    non_cancellable = {OrderStatus.SHIPPED, OrderStatus.DELIVERED}
    if OrderStatus(order.status) in non_cancellable:
        raise HTTPException(status_code=409, detail=f"Cannot cancel order in '{order.status}' state")

    order = await update_order_status(session, order_id, "cancelled")
    await session.commit()

    publish_event(
        topic="order.cancelled",
        key=str(order.id),
        value={"order_id": str(order.id), "status": "cancelled"},
    )

    return order
