"""Warehouse endpoints — goods movements, inventory, driver management."""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InventoryReservation
from app.db.repository import create_driver, soft_delete_driver
from app.db.session import get_session
from app.kafka.producer import publish_event
from app.models.schemas import DriverCreate, GoodsMovement

logger = structlog.get_logger()

router = APIRouter()


@router.post("/goods-in", status_code=202)
async def record_goods_in(body: GoodsMovement, session: AsyncSession = Depends(get_session)):
    """Record inbound goods receipt — publishes event for downstream processing."""
    publish_event(
        topic="warehouse.goods-in",
        key=body.sku,
        value={"sku": body.sku, "quantity": body.quantity, "reference": body.reference_number},
    )
    return {"detail": "Goods-in accepted", "sku": body.sku, "quantity": body.quantity}


@router.post("/goods-out", status_code=202)
async def record_goods_out(body: GoodsMovement, session: AsyncSession = Depends(get_session)):
    """Record outbound goods dispatch — publishes event for downstream processing."""
    publish_event(
        topic="warehouse.goods-out",
        key=body.sku,
        value={"sku": body.sku, "quantity": body.quantity, "reference": body.reference_number},
    )
    return {"detail": "Goods-out accepted", "sku": body.sku, "quantity": body.quantity}


@router.get("/inventory")
async def list_inventory(session: AsyncSession = Depends(get_session)):
    """List current inventory levels (aggregated from order reservations)."""
    stmt = (
        select(
            InventoryReservation.sku,
            func.sum(InventoryReservation.quantity).label("total_quantity"),
        )
        .group_by(InventoryReservation.sku)
    )
    result = await session.execute(stmt)
    return [{"sku": row.sku, "quantity": row.total_quantity} for row in result.all()]


@router.post("/drivers", status_code=201)
async def add_driver(body: DriverCreate, session: AsyncSession = Depends(get_session)):
    """Register a new driver or vendor."""
    driver = await create_driver(
        session,
        name=body.name,
        phone=body.phone,
        vendor=body.vendor,
        vehicle_plate=body.vehicle_plate,
    )
    await session.commit()
    return {"id": str(driver.id), "name": driver.name}


@router.delete("/drivers/{driver_id}")
async def remove_driver(driver_id: UUID, session: AsyncSession = Depends(get_session)):
    """Soft-delete a driver or vendor."""
    driver = await soft_delete_driver(session, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    await session.commit()
    return {"detail": "Driver removed"}
