"""SQLAlchemy ORM models mapped to redesigned PostgreSQL schema."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    customer_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_category = Column(Enum("b2b", "b2c", name="customer_type"), nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    ward = Column(String, nullable=True)
    city_province = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Company(Base):
    __tablename__ = "companies"

    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.customer_id"), primary_key=True)
    company_name = Column(String, nullable=False)
    tax_id = Column(String, nullable=False, unique=True)


class Individual(Base):
    __tablename__ = "individuals"

    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.customer_id"), primary_key=True)
    full_name = Column(String, nullable=False)
    ssi = Column(String, nullable=False, unique=True)


class Product(Base):
    __tablename__ = "products"

    product_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku = Column(String, nullable=False, unique=True)
    product_name = Column(String, nullable=False)
    category = Column(String, nullable=True)
    weight_per_unit_kg = Column(Float, nullable=False)


class Warehouse(Base):
    __tablename__ = "warehouses"

    warehouse_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    warehouse_name = Column(String, nullable=False)
    location = Column(String, nullable=False)


class Vendor(Base):
    __tablename__ = "vendors"

    vendor_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    tax_no = Column(String, nullable=False, unique=True)
    address = Column(Text, nullable=True)


class Vehicle(Base):
    __tablename__ = "vehicles"

    vehicle_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("vendors.vendor_id"), nullable=False)
    plate_number = Column(String, nullable=False, unique=True)
    vehicle_type = Column(String, nullable=False)
    capacity_quantity = Column(Integer, nullable=False)


class Driver(Base):
    __tablename__ = "drivers"

    driver_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = Column(String, nullable=False)
    license_number = Column(String, nullable=False, unique=True)
    phone = Column(String, nullable=True)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("vendors.vendor_id"), nullable=True)
    active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class ShipmentRequest(Base):
    __tablename__ = "shipment_requests"

    request_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_type = Column(Enum("b2b", "b2c", name="shipment_request_type"), nullable=False)
    request_date = Column(Date, nullable=False)
    origin = Column(String, nullable=False)
    destination = Column(String, nullable=False)
    planned_date = Column(Date, nullable=True)


class B2BRequest(Base):
    __tablename__ = "b2b_requests"

    request_id = Column(UUID(as_uuid=True), ForeignKey("shipment_requests.request_id"), primary_key=True)
    driver_id = Column(UUID(as_uuid=True), ForeignKey("drivers.driver_id"), nullable=False)
    loading_dock = Column(String, nullable=True)
    dispatch_time = Column(DateTime(timezone=True), nullable=True)


class B2CRequest(Base):
    __tablename__ = "b2c_requests"

    request_id = Column(UUID(as_uuid=True), ForeignKey("shipment_requests.request_id"), primary_key=True)
    vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.vehicle_id"), nullable=False)
    recipient_name = Column(String, nullable=False)
    contact_number = Column(String, nullable=True)
    scheduled_time = Column(DateTime(timezone=True), nullable=True)


class CheckInRecord(Base):
    __tablename__ = "check_in_records"

    check_in_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("b2c_requests.request_id"), nullable=False, unique=True)
    gate = Column(String, nullable=True)
    check_in_time = Column(DateTime(timezone=True), nullable=False)
    delay_minutes = Column(Integer, nullable=False, default=0)
    notes = Column(Text, nullable=True)


class DeliveryOrder(Base):
    __tablename__ = "delivery_orders"

    delivery_order_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    warehouse_id = Column(UUID(as_uuid=True), ForeignKey("warehouses.warehouse_id"), nullable=False)
    request_id = Column(UUID(as_uuid=True), ForeignKey("shipment_requests.request_id"), nullable=False, unique=True)
    delivery_date = Column(Date, nullable=True)
    status = Column(
        Enum("planned", "assigned", "in_transit", "delivered", "failed", name="delivery_status"),
        nullable=False,
        default="planned",
    )


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
        Enum("pending", "confirmed", "allocated", "packed", "in_transit", "delivered", "cancelled", "exception", name="order_status"),
        nullable=False,
        default="pending",
    )
    total_amount = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    items = relationship("OrderItem", back_populates="sale_order", cascade="all, delete-orphan")
    statuses = relationship("SaleOrderStatus", back_populates="sale_order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    sale_order_id = Column(UUID(as_uuid=True), ForeignKey("sale_orders.sale_order_id"), primary_key=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.product_id"), primary_key=True)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    weight_per_unit_kg = Column(Float, nullable=False)
    total_kg = Column(Float, nullable=False)

    sale_order = relationship("SaleOrder", back_populates="items")


class SaleOrderStatus(Base):
    __tablename__ = "sale_order_status"

    status_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sale_order_id = Column(UUID(as_uuid=True), ForeignKey("sale_orders.sale_order_id"), nullable=False)
    status = Column(Enum("pending", "confirmed", "allocated", "packed", "in_transit", "delivered", "cancelled", "exception", name="order_status"), nullable=False)
    status_timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    remarks = Column(Text, nullable=True)

    sale_order = relationship("SaleOrder", back_populates="statuses")


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


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aggregate_type = Column(String, nullable=False)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False)
    event_type = Column(String, nullable=False)
    payload = Column(JSONB, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String, nullable=False)
    events = Column(JSONB, nullable=False)
    secret = Column(String, nullable=True)
    active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
