"""Pydantic schemas — canonical API models."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class OrderStatus(str, Enum):
    RECEIVED = "received"
    VALIDATED = "validated"
    ERP_SYNCED = "erp_synced"
    ALLOCATED = "allocated"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    EXCEPTION = "exception"


class ShipmentStatus(str, Enum):
    REQUESTED = "requested"
    CREATED = "created"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    EXCEPTION = "exception"


class OrderItemCreate(BaseModel):
    sku: str
    product_name: str
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0)


class OrderCreate(BaseModel):
    external_order_id: str
    channel: str
    customer_name: str
    customer_email: str | None = None
    shipping_address: str
    items: list[OrderItemCreate]


class OrderItemResponse(BaseModel):
    id: UUID
    sku: str
    product_name: str
    quantity: int
    unit_price: float

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: UUID
    external_order_id: str
    channel: str
    status: OrderStatus
    customer_name: str
    shipping_address: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ShipmentResponse(BaseModel):
    id: UUID
    order_id: UUID
    carrier: str | None = None
    tracking_number: str | None = None
    status: ShipmentStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TrackingEvent(BaseModel):
    status: ShipmentStatus
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
    name: str
    phone: str | None = None
    vendor: str | None = None
    vehicle_plate: str | None = None


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
