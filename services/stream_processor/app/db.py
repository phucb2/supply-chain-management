"""Async DB access for stream processor against redesigned schema."""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Column, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text, select, update
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship, selectinload

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class SaleOrder(Base):
    __tablename__ = "sale_orders"

    sale_order_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_order_id = Column(String, nullable=False, unique=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.customer_id"), nullable=False)
    delivery_order_id = Column(UUID(as_uuid=True), ForeignKey("delivery_orders.delivery_order_id"), nullable=False)
    source = Column(String, nullable=False)
    order_date = Column(Date, nullable=False)
    req_delivery_date = Column(Date, nullable=False)
    status = Column(
        Enum("pending", "confirmed", "allocated", "packed", "in_transit", "delivered", "cancelled", "exception", name="order_status", create_type=False),
        nullable=False,
        default="pending",
    )
    total_amount = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    items = relationship("OrderItem", back_populates="sale_order")


class Product(Base):
    __tablename__ = "products"

    product_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku = Column(String, nullable=False, unique=True)
    product_name = Column(String, nullable=False)
    weight_per_unit_kg = Column(Float, nullable=False)


class OrderItem(Base):
    __tablename__ = "order_items"

    sale_order_id = Column(UUID(as_uuid=True), ForeignKey("sale_orders.sale_order_id"), primary_key=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.product_id"), primary_key=True)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    weight_per_unit_kg = Column(Float, nullable=False)
    total_kg = Column(Float, nullable=False)
    sale_order = relationship("SaleOrder", back_populates="items")
    product = relationship("Product")


class SaleOrderStatus(Base):
    __tablename__ = "sale_order_status"

    status_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sale_order_id = Column(UUID(as_uuid=True), ForeignKey("sale_orders.sale_order_id"), nullable=False)
    status = Column(Enum("pending", "confirmed", "allocated", "packed", "in_transit", "delivered", "cancelled", "exception", name="order_status", create_type=False), nullable=False)
    status_timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    remarks = Column(Text, nullable=True)


class DeliveryOrder(Base):
    __tablename__ = "delivery_orders"

    delivery_order_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("shipment_requests.request_id"), nullable=False, unique=True)
    status = Column(Enum("planned", "assigned", "in_transit", "delivered", "failed", name="delivery_status", create_type=False), nullable=False, default="planned")
    delivery_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class ShipmentRequest(Base):
    __tablename__ = "shipment_requests"

    request_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_type = Column(Enum("b2b", "b2c", name="shipment_request_type", create_type=False), nullable=False)
    request_date = Column(Date, nullable=False)
    origin = Column(String, nullable=False)
    destination = Column(String, nullable=False)


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sale_order_id = Column(UUID(as_uuid=True), ForeignKey("sale_orders.sale_order_id"), nullable=False)
    delivery_order_id = Column(UUID(as_uuid=True), ForeignKey("delivery_orders.delivery_order_id"), nullable=False)
    predicted_eta_hours = Column(Float, nullable=False)
    model_version = Column(String, nullable=False)
    input_features = Column(JSONB, nullable=True)
    predicted_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class PredictionActual(Base):
    __tablename__ = "prediction_actuals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sale_order_id = Column(UUID(as_uuid=True), ForeignKey("sale_orders.sale_order_id"), nullable=False)
    prediction_id = Column(UUID(as_uuid=True), ForeignKey("predictions.id"), nullable=False)
    actual_eta_hours = Column(Float, nullable=False)
    absolute_error = Column(Float, nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String, nullable=False)
    events = Column(JSONB, nullable=False)
    secret = Column(String, nullable=True)
    active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False)


async def get_order(order_id: uuid.UUID) -> SaleOrder | None:
    async with async_session() as session:
        result = await session.execute(
            select(SaleOrder).options(selectinload(SaleOrder.items).selectinload(OrderItem.product)).where(SaleOrder.sale_order_id == order_id)
        )
        return result.scalar_one_or_none()


async def update_order_status(order_id: uuid.UUID, new_status: str) -> SaleOrder | None:
    async with async_session() as session:
        await session.execute(
            update(SaleOrder).where(SaleOrder.sale_order_id == order_id).values(
                status=new_status, updated_at=datetime.now(timezone.utc),
            )
        )
        session.add(SaleOrderStatus(sale_order_id=order_id, status=new_status, remarks="stream update"))
        await session.commit()
        return await get_order(order_id)


async def create_order_event(order_id: uuid.UUID, event_type: str, payload: dict | None = None) -> None:
    status_map = {
        "order.received": "pending",
        "order.validated": "confirmed",
        "order.allocated": "allocated",
        "order.shipped": "in_transit",
        "order.delivered": "delivered",
        "order.cancelled": "cancelled",
        "order.exception": "exception",
    }
    mapped = status_map.get(event_type, payload.get("new_status") if payload else None)
    if mapped is None:
        return
    async with async_session() as session:
        session.add(SaleOrderStatus(sale_order_id=order_id, status=mapped, remarks=event_type))
        await session.commit()


async def create_shipment(*, order_id: uuid.UUID, carrier: str, tracking_number: str, label_url: str | None = None) -> DeliveryOrder:
    del carrier, tracking_number, label_url
    async with async_session() as session:
        result = await session.execute(select(SaleOrder.delivery_order_id).where(SaleOrder.sale_order_id == order_id))
        delivery_order_id = result.scalar_one()
        row = await session.execute(select(DeliveryOrder).where(DeliveryOrder.delivery_order_id == delivery_order_id))
        delivery = row.scalar_one()
        delivery.status = "assigned"
        await session.commit()
        await session.refresh(delivery)
        return delivery


async def create_inventory_reservation(*, order_id: uuid.UUID, sku: str, quantity: int):
    del order_id, sku, quantity
    class Placeholder:
        id = uuid.uuid4()
    return Placeholder()


async def get_shipment(shipment_id: uuid.UUID) -> DeliveryOrder | None:
    async with async_session() as session:
        result = await session.execute(select(DeliveryOrder).where(DeliveryOrder.delivery_order_id == shipment_id))
        return result.scalar_one_or_none()


async def update_shipment_status(shipment_id: uuid.UUID, new_status: str) -> DeliveryOrder | None:
    mapping = {
        "picked_up": "in_transit",
        "in_transit": "in_transit",
        "out_for_delivery": "in_transit",
        "delivered": "delivered",
        "exception": "failed",
    }
    async with async_session() as session:
        await session.execute(
            update(DeliveryOrder).where(DeliveryOrder.delivery_order_id == shipment_id).values(
                status=mapping.get(new_status, "in_transit"),
                delivery_date=date.today() if new_status == "delivered" else None,
            )
        )
        await session.commit()
        return await get_shipment(shipment_id)


async def get_webhook_subscriptions_for_event(event_type: str) -> list[WebhookSubscription]:
    async with async_session() as session:
        result = await session.execute(select(WebhookSubscription).where(WebhookSubscription.active == 1))
        all_subs = list(result.scalars().all())
        return [s for s in all_subs if event_type in s.events]


async def save_prediction(*, shipment_id: uuid.UUID, predicted_eta_hours: float, model_version: str, input_features: dict | None = None) -> Prediction:
    async with async_session() as session:
        result = await session.execute(select(SaleOrder).where(SaleOrder.delivery_order_id == shipment_id).limit(1))
        order = result.scalar_one()
        prediction = Prediction(
            sale_order_id=order.sale_order_id,
            delivery_order_id=shipment_id,
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
            select(Prediction).where(Prediction.delivery_order_id == shipment_id).order_by(Prediction.predicted_at.desc())
        )
        return result.scalar_one_or_none()


async def save_prediction_actual(*, shipment_id: uuid.UUID, prediction_id: uuid.UUID, actual_eta_hours: float, absolute_error: float) -> PredictionActual:
    async with async_session() as session:
        prediction = await session.get(Prediction, prediction_id)
        actual = PredictionActual(
            sale_order_id=prediction.sale_order_id,
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
            update(DeliveryOrder).where(DeliveryOrder.delivery_order_id == shipment_id).values(
                delivery_date=delivered_at.date(), status="delivered",
            )
        )
        await session.commit()


async def get_shipment_with_order(
    shipment_id: uuid.UUID,
) -> tuple[DeliveryOrder | None, SaleOrder | None, str]:
    """Return delivery row, sale order, and request_type (b2b/b2c) for ML — matches training FEATURE_QUERY carrier column."""
    async with async_session() as session:
        result = await session.execute(select(DeliveryOrder).where(DeliveryOrder.delivery_order_id == shipment_id))
        shipment = result.scalar_one_or_none()
        if shipment is None:
            return None, None, "unknown"
        order_result = await session.execute(
            select(SaleOrder)
            .options(selectinload(SaleOrder.items).selectinload(OrderItem.product))
            .where(SaleOrder.delivery_order_id == shipment_id)
            .limit(1)
        )
        order = order_result.scalar_one_or_none()
        req_row = await session.execute(
            select(ShipmentRequest.request_type).where(ShipmentRequest.request_id == shipment.request_id)
        )
        rt = req_row.scalar_one_or_none()
        carrier_for_model = "unknown"
        if rt is not None:
            carrier_for_model = getattr(rt, "value", str(rt))
        return shipment, order, carrier_for_model
