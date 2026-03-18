"""Shipment tracking agent: status sync, webhook dispatch, notification triggers."""

import logging
import uuid

from app.main import app
from app.models import ShipmentStatusUpdated

logger = logging.getLogger(__name__)

shipment_status_topic = app.topic("shipment.status-updated", value_type=ShipmentStatusUpdated)


@app.agent(shipment_status_topic)
async def track_shipment(stream):
    async for event in stream:
        shipment_id = event.shipment_id
        order_id = event.order_id
        new_status = event.status

        logger.info("Tracking update: shipment %s → %s", shipment_id, new_status)

        try:
            from app.db import (
                get_shipment,
                update_shipment_status,
                update_order_status,
                create_order_event,
            )
            from app.webhooks import dispatch_webhooks

            sid = uuid.UUID(shipment_id)
            oid = uuid.UUID(order_id)

            shipment = await get_shipment(sid)
            if not shipment:
                logger.error("Shipment %s not found", shipment_id)
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
                logger.info("Order %s marked as delivered", order_id)

            elif new_status == "exception":
                await update_order_status(oid, "exception")
                logger.warning("Order %s marked as exception due to shipment", order_id)

            await dispatch_webhooks("shipment.status-updated", {
                "shipment_id": shipment_id,
                "order_id": order_id,
                "status": new_status,
                "location": event.location,
                "timestamp": event.timestamp,
            })

        except Exception:
            logger.exception("Error processing shipment tracking for %s", shipment_id)
