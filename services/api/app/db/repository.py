"""Repository layer — async DB access for orders, shipments, events, and webhooks."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Driver,
    InventoryReservation,
    Order,
    OrderEvent,
    OrderItem,
    Shipment,
    ShipmentPackage,
    WebhookSubscription,
)


# ── Orders ───────────────────────────────────────────────────────────────────

async def create_order(
    session: AsyncSession,
    *,
    external_order_id: str,
    channel: str,
    customer_name: str,
    customer_email: str | None,
    shipping_address: str,
    raw_payload: dict | None,
    items: list[dict],
) -> tuple[Order, bool]:
    """Insert order with ON CONFLICT DO NOTHING. Returns (order, created)."""
    order_id = uuid.uuid4()

    stmt = (
        pg_insert(Order)
        .values(
            id=order_id,
            external_order_id=external_order_id,
            channel=channel,
            customer_name=customer_name,
            customer_email=customer_email,
            shipping_address=shipping_address,
            raw_payload=raw_payload,
            status="received",
        )
        .on_conflict_do_nothing(index_elements=["external_order_id"])
        .returning(Order.id)
    )
    result = await session.execute(stmt)
    row = result.fetchone()

    if row is None:
        existing = await session.execute(
            select(Order).where(Order.external_order_id == external_order_id)
        )
        return existing.scalar_one(), False

    for item in items:
        session.add(OrderItem(
            order_id=order_id,
            sku=item["sku"],
            product_name=item["product_name"],
            quantity=item["quantity"],
            unit_price=item["unit_price"],
        ))

    await session.flush()

    order = await session.execute(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.id == order_id)
    )
    return order.scalar_one(), True


async def get_order(session: AsyncSession, order_id: uuid.UUID) -> Order | None:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.events))
        .where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


async def list_orders(
    session: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    status_filter: str | None = None,
    channel_filter: str | None = None,
) -> list[Order]:
    stmt = select(Order).offset(skip).limit(limit).order_by(Order.created_at.desc())
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    if channel_filter:
        stmt = stmt.where(Order.channel == channel_filter)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_order_status(
    session: AsyncSession,
    order_id: uuid.UUID,
    new_status: str,
) -> Order | None:
    await session.execute(
        update(Order)
        .where(Order.id == order_id)
        .values(status=new_status, updated_at=datetime.now(timezone.utc))
    )
    await create_order_event(session, order_id, f"order.{new_status}", {"new_status": new_status})
    await session.flush()
    return await get_order(session, order_id)


# ── Order Events ─────────────────────────────────────────────────────────────

async def create_order_event(
    session: AsyncSession,
    order_id: uuid.UUID,
    event_type: str,
    payload: dict | None = None,
) -> OrderEvent:
    event = OrderEvent(order_id=order_id, event_type=event_type, payload=payload)
    session.add(event)
    await session.flush()
    return event


# ── Shipments ────────────────────────────────────────────────────────────────

async def create_shipment(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    carrier: str,
    tracking_number: str,
    label_url: str | None = None,
) -> Shipment:
    shipment = Shipment(
        order_id=order_id,
        carrier=carrier,
        tracking_number=tracking_number,
        status="created",
    )
    session.add(shipment)
    await session.flush()

    if label_url:
        session.add(ShipmentPackage(shipment_id=shipment.id, label_url=label_url))
        await session.flush()

    return shipment


async def get_shipment(session: AsyncSession, shipment_id: uuid.UUID) -> Shipment | None:
    result = await session.execute(
        select(Shipment)
        .options(selectinload(Shipment.packages))
        .where(Shipment.id == shipment_id)
    )
    return result.scalar_one_or_none()


async def update_shipment_status(
    session: AsyncSession,
    shipment_id: uuid.UUID,
    new_status: str,
) -> Shipment | None:
    await session.execute(
        update(Shipment)
        .where(Shipment.id == shipment_id)
        .values(status=new_status, updated_at=datetime.now(timezone.utc))
    )
    await session.flush()
    return await get_shipment(session, shipment_id)


async def get_shipment_tracking_events(
    session: AsyncSession,
    shipment_id: uuid.UUID,
) -> list[OrderEvent]:
    shipment = await get_shipment(session, shipment_id)
    if not shipment:
        return []
    result = await session.execute(
        select(OrderEvent)
        .where(
            OrderEvent.order_id == shipment.order_id,
            OrderEvent.event_type.like("shipment.%"),
        )
        .order_by(OrderEvent.created_at)
    )
    return list(result.scalars().all())


# ── Inventory Reservations ───────────────────────────────────────────────────

async def create_inventory_reservation(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    sku: str,
    quantity: int,
) -> InventoryReservation:
    reservation = InventoryReservation(order_id=order_id, sku=sku, quantity=quantity, status="reserved")
    session.add(reservation)
    await session.flush()
    return reservation


# ── Drivers ──────────────────────────────────────────────────────────────────

async def create_driver(session: AsyncSession, *, name: str, phone: str | None, vendor: str | None, vehicle_plate: str | None) -> Driver:
    driver = Driver(name=name, phone=phone, vendor=vendor, vehicle_plate=vehicle_plate)
    session.add(driver)
    await session.flush()
    return driver


async def soft_delete_driver(session: AsyncSession, driver_id: uuid.UUID) -> Driver | None:
    result = await session.execute(select(Driver).where(Driver.id == driver_id))
    driver = result.scalar_one_or_none()
    if driver:
        driver.deleted_at = datetime.now(timezone.utc)
        driver.active = 0
        await session.flush()
    return driver


# ── Webhooks ─────────────────────────────────────────────────────────────────

async def create_webhook_subscription(
    session: AsyncSession,
    *,
    url: str,
    events: list[str],
    secret: str | None = None,
) -> WebhookSubscription:
    sub = WebhookSubscription(url=url, events=events, secret=secret)
    session.add(sub)
    await session.flush()
    return sub


async def list_webhook_subscriptions(session: AsyncSession) -> list[WebhookSubscription]:
    result = await session.execute(
        select(WebhookSubscription).where(WebhookSubscription.active == 1)
    )
    return list(result.scalars().all())


async def get_webhook_subscriptions_for_event(
    session: AsyncSession,
    event_type: str,
) -> list[WebhookSubscription]:
    all_subs = await list_webhook_subscriptions(session)
    return [s for s in all_subs if event_type in s.events]
