"""Faust record models for Kafka message serialization."""

import faust


class OrderReceived(faust.Record):
    order_id: str
    external_order_id: str
    channel: str
    customer_name: str
    shipping_address: str
    items: list[dict]


class OrderValidated(faust.Record):
    order_id: str
    external_order_id: str


class OrderAllocated(faust.Record):
    order_id: str
    reservations: list[dict]


class ShipmentRequested(faust.Record):
    order_id: str
    delivery_order_id: str


class ShipmentStatusUpdated(faust.Record):
    delivery_order_id: str
    order_id: str
    status: str
    location: str | None = None
    timestamp: str | None = None


class OrderException(faust.Record):
    order_id: str
    reason: str
    original_event: str | None = None


class ShipmentCreated(faust.Record):
    order_id: str
    delivery_order_id: str
    carrier: str
    tracking_number: str


class EtaPredicted(faust.Record):
    delivery_order_id: str
    predicted_eta_hours: float
    model_version: str
    predicted_at: str
