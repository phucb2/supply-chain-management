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
    shipment_id: str


class ShipmentStatusUpdated(faust.Record):
    shipment_id: str
    order_id: str
    status: str
    location: str | None = None
    timestamp: str | None = None


class OrderException(faust.Record):
    order_id: str
    reason: str
    original_event: str | None = None
