"""Async DB access for the stream processor — mirrors API repository patterns."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Import ORM models from a shared location — stream processor reuses the same
# DB schema as the API service, so we define lightweight local mirrors.
from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_order_id = Column(String, nullable=False, unique=True)
    channel = Column(String, nullable=False)
    status = Column(
        Enum("received", "validated", "erp_synced", "allocated", "shipped", "delivered", "cancelled", "exception",
             name="order_status", create_type=False),
        nullable=False, default="received",
    )
    customer_name = Column(String, nullable=False)
    customer_email = Column(String, nullable=True)
    shipping_address = Column(Text, nullable=False)
    raw_payload = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    sku = Column(String, nullable=False)
    product_name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    order = relationship("Order", back_populates="items")


class OrderEvent(Base):
    __tablename__ = "order_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    event_type = Column(String, nullable=False)
    payload = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Shipment(Base):
    __tablename__ = "shipments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    carrier = Column(String, nullable=True)
    tracking_number = Column(String, nullable=True)
    status = Column(
        Enum("requested", "created", "picked_up", "in_transit", "out_for_delivery", "delivered", "exception",
             name="shipment_status", create_type=False),
        nullable=False, default="requested",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    packages = relationship("ShipmentPackage", back_populates="shipment")


class ShipmentPackage(Base):
    __tablename__ = "shipment_packages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=False)
    weight = Column(Float, nullable=True)
    dimensions = Column(String, nullable=True)
    label_url = Column(String, nullable=True)
    shipment = relationship("Shipment", back_populates="packages")


class InventoryReservation(Base):
    __tablename__ = "inventory_reservations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    sku = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(
        Enum("reserved", "committed", "released", name="reservation_status", create_type=False),
        nullable=False, default="reserved",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String, nullable=False)
    events = Column(JSONB, nullable=False)
    secret = Column(String, nullable=True)
    active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False)


class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=False)
    predicted_eta_hours = Column(Float, nullable=False)
    model_version = Column(String, nullable=False)
    input_features = Column(JSONB, nullable=True)
    predicted_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class PredictionActual(Base):
    __tablename__ = "prediction_actuals"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=False)
    prediction_id = Column(UUID(as_uuid=True), ForeignKey("predictions.id"), nullable=False)
    actual_eta_hours = Column(Float, nullable=False)
    absolute_error = Column(Float, nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


# ── Query helpers ────────────────────────────────────────────────────────────

async def get_order(order_id: uuid.UUID) -> Order | None:
    async with async_session() as session:
        result = await session.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )
        return result.scalar_one_or_none()


async def update_order_status(order_id: uuid.UUID, new_status: str) -> Order | None:
    async with async_session() as session:
        await session.execute(
            update(Order)
            .where(Order.id == order_id)
            .values(status=new_status, updated_at=datetime.now(timezone.utc))
        )
        event = OrderEvent(order_id=order_id, event_type=f"order.{new_status}", payload={"new_status": new_status})
        session.add(event)
        await session.commit()
        return await get_order(order_id)


async def create_order_event(order_id: uuid.UUID, event_type: str, payload: dict | None = None) -> None:
    async with async_session() as session:
        session.add(OrderEvent(order_id=order_id, event_type=event_type, payload=payload))
        await session.commit()


async def create_shipment(
    *,
    order_id: uuid.UUID,
    carrier: str,
    tracking_number: str,
    label_url: str | None = None,
) -> Shipment:
    async with async_session() as session:
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
        await session.commit()
        await session.refresh(shipment)
        return shipment


async def create_inventory_reservation(
    *,
    order_id: uuid.UUID,
    sku: str,
    quantity: int,
) -> InventoryReservation:
    async with async_session() as session:
        reservation = InventoryReservation(order_id=order_id, sku=sku, quantity=quantity)
        session.add(reservation)
        await session.commit()
        await session.refresh(reservation)
        return reservation


async def get_shipment(shipment_id: uuid.UUID) -> Shipment | None:
    async with async_session() as session:
        result = await session.execute(
            select(Shipment).options(selectinload(Shipment.packages)).where(Shipment.id == shipment_id)
        )
        return result.scalar_one_or_none()


async def update_shipment_status(shipment_id: uuid.UUID, new_status: str) -> Shipment | None:
    async with async_session() as session:
        await session.execute(
            update(Shipment)
            .where(Shipment.id == shipment_id)
            .values(status=new_status, updated_at=datetime.now(timezone.utc))
        )
        await session.commit()
        return await get_shipment(shipment_id)


async def get_webhook_subscriptions_for_event(event_type: str) -> list[WebhookSubscription]:
    async with async_session() as session:
        result = await session.execute(
            select(WebhookSubscription).where(WebhookSubscription.active == 1)
        )
        all_subs = list(result.scalars().all())
        return [s for s in all_subs if event_type in s.events]


# ── ML query helpers ─────────────────────────────────────────────────────────

async def save_prediction(
    *,
    shipment_id: uuid.UUID,
    predicted_eta_hours: float,
    model_version: str,
    input_features: dict | None = None,
) -> Prediction:
    async with async_session() as session:
        prediction = Prediction(
            shipment_id=shipment_id,
            predicted_eta_hours=predicted_eta_hours,
            model_version=model_version,
            input_features=input_features,
        )
        session.add(prediction)
        await session.commit()
        await session.refresh(prediction)
        return prediction


async def get_prediction_for_shipment(shipment_id: uuid.UUID) -> Prediction | None:
    async with async_session() as session:
        result = await session.execute(
            select(Prediction)
            .where(Prediction.shipment_id == shipment_id)
            .order_by(Prediction.predicted_at.desc())
        )
        return result.scalar_one_or_none()


async def save_prediction_actual(
    *,
    shipment_id: uuid.UUID,
    prediction_id: uuid.UUID,
    actual_eta_hours: float,
    absolute_error: float,
) -> PredictionActual:
    async with async_session() as session:
        actual = PredictionActual(
            shipment_id=shipment_id,
            prediction_id=prediction_id,
            actual_eta_hours=actual_eta_hours,
            absolute_error=absolute_error,
        )
        session.add(actual)
        await session.commit()
        await session.refresh(actual)
        return actual


async def set_shipment_delivered_at(shipment_id: uuid.UUID, delivered_at: datetime) -> None:
    async with async_session() as session:
        await session.execute(
            update(Shipment)
            .where(Shipment.id == shipment_id)
            .values(delivered_at=delivered_at)
        )
        await session.commit()


async def get_shipment_with_order(shipment_id: uuid.UUID) -> tuple[Shipment | None, Order | None]:
    """Fetch a shipment and its parent order in one round-trip."""
    async with async_session() as session:
        result = await session.execute(
            select(Shipment).options(selectinload(Shipment.packages)).where(Shipment.id == shipment_id)
        )
        shipment = result.scalar_one_or_none()
        if shipment is None:
            return None, None
        order_result = await session.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == shipment.order_id)
        )
        order = order_result.scalar_one_or_none()
        return shipment, order
