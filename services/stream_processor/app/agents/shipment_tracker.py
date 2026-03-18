"""Shipment tracking agent: status sync, webhook dispatch, notification triggers."""

import uuid

import structlog
from opentelemetry import trace

from app.main import app
from app.models import ShipmentStatusUpdated
from observability import (
    orders_delivered,
    orders_exception,
    shipments_delivered,
    shipments_exception,
)

logger = structlog.get_logger()
tracer = trace.get_tracer(__name__)

shipment_status_topic = app.topic("shipment.status-updated", value_type=ShipmentStatusUpdated)


@app.agent(shipment_status_topic)
async def track_shipment(stream):
    async for event in stream:
        shipment_id = event.shipment_id
        order_id = event.order_id
        new_status = event.status

        with tracer.start_as_current_span(
            "shipment.track",
            attributes={
                "shipment.id": shipment_id,
                "shipment.status": new_status,
                "order.id": order_id,
            },
        ):
            logger.info("shipment_tracking_update", shipment_id=shipment_id, status=new_status)

            try:
                from app.db import (
                    create_order_event,
                    get_shipment,
                    update_order_status,
                    update_shipment_status,
                )
                from app.webhooks import dispatch_webhooks

                sid = uuid.UUID(shipment_id)
                oid = uuid.UUID(order_id)

                shipment = await get_shipment(sid)
                if not shipment:
                    logger.error("shipment_not_found", shipment_id=shipment_id)
                    continue

                await update_shipment_status(sid, new_status)

                await create_order_event(oid, "shipment.status-updated", {
                    "shipment_id": shipment_id,
                    "status": new_status,
                    "location": event.location,
                    "timestamp": event.timestamp,
                })

                if new_status == "delivered":
                    await update_order_status(oid, "delivered")
                    await create_order_event(oid, "order.delivered", {
                        "shipment_id": shipment_id,
                    })
                    shipments_delivered.add(1, {"carrier": shipment.carrier or "unknown"})
                    orders_delivered.add(1)
                    logger.info("order_delivered", order_id=order_id, shipment_id=shipment_id)

                elif new_status == "exception":
                    await update_order_status(oid, "exception")
                    shipments_exception.add(1, {"carrier": shipment.carrier or "unknown"})
                    orders_exception.add(1)
                    logger.warning("shipment_exception", order_id=order_id, shipment_id=shipment_id)

                await dispatch_webhooks("shipment.status-updated", {
                    "shipment_id": shipment_id,
                    "order_id": order_id,
                    "status": new_status,
                    "location": event.location,
                    "timestamp": event.timestamp,
                })

            except Exception:
                logger.exception("shipment_tracking_error", shipment_id=shipment_id)
