"""Pydantic schemas for redesigned sales and delivery data model."""

from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class CustomerCategory(str, Enum):
    B2B = "b2b"
    B2C = "b2c"


class OrderStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ALLOCATED = "allocated"
    PACKED = "packed"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    EXCEPTION = "exception"


class DeliveryStatus(str, Enum):
    PLANNED = "planned"
    ASSIGNED = "assigned"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    FAILED = "failed"


class ShipmentRequestType(str, Enum):
    B2B = "b2b"
    B2C = "b2c"


class OrderItemCreate(BaseModel):
    sku: str
    product_name: str
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0)
    weight_per_unit_kg: float = Field(gt=0)


class OrderCreate(BaseModel):
    external_order_id: str
    source: str
    customer_category: CustomerCategory
    customer_name: str
    customer_email: str | None = None
    shipping_address: str
    req_delivery_date: date
    request_type: ShipmentRequestType = ShipmentRequestType.B2C
    origin: str = "main_warehouse"
    destination: str
    items: list[OrderItemCreate]


class OrderResponse(BaseModel):
    sale_order_id: UUID
    external_order_id: str
    source: str
    status: OrderStatus
    customer_id: UUID
    delivery_order_id: UUID
    req_delivery_date: date
    created_at: datetime

    model_config = {"from_attributes": True}


class ShipmentResponse(BaseModel):
    delivery_order_id: UUID
    request_id: UUID
    status: DeliveryStatus
    delivery_date: date | None = None

    model_config = {"from_attributes": True}


class TrackingEvent(BaseModel):
    status: str
    location: str | None = None
    notes: str | None = None
    timestamp: datetime | None = None


class GoodsMovement(BaseModel):
    sku: str
    quantity: int = Field(gt=0)
    warehouse_location: str | None = None
    reference_number: str | None = None
    notes: str | None = None


class DriverCreate(BaseModel):
    full_name: str
    license_number: str
    phone: str | None = None
    vendor_id: UUID | None = None


class WebhookSubscription(BaseModel):
    url: str
    events: list[str]
    secret: str | None = None


class WebhookSubscriptionResponse(BaseModel):
    id: UUID
    url: str
    events: list[str]
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
