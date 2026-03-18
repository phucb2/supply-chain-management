"""Order processing pipeline: validate → ERP sync → allocate inventory → create shipment."""

import logging
import uuid

from app.main import app
from app.models import OrderReceived

logger = logging.getLogger(__name__)

order_received_topic = app.topic("order.received", value_type=OrderReceived)
order_validated_topic = app.topic("order.validated", value_serializer="json")
order_erp_created_topic = app.topic("order.erp.created", value_serializer="json")
order_allocated_topic = app.topic("order.allocated", value_serializer="json")
shipment_created_topic = app.topic("shipment.created", value_serializer="json")
order_exception_topic = app.topic("order.exception", value_serializer="json")
dlq_topic = app.topic("dlq.order.received", value_serializer="json")


@app.agent(order_received_topic)
async def process_order(stream):
    async for event in stream:
        order_id = event.order_id
        logger.info("Pipeline started for order %s", order_id)

        try:
            await _run_pipeline(event)
        except Exception:
            logger.exception("Permanent failure processing order %s — sending to DLQ", order_id)
            try:
                from app.db import update_order_status, create_order_event
                await update_order_status(uuid.UUID(order_id), "exception")
                await create_order_event(
                    uuid.UUID(order_id), "order.exception",
                    {"reason": "Unhandled pipeline error"},
                )
            except Exception:
                logger.exception("Failed to update order status to exception")

            await dlq_topic.send(value={
                "order_id": order_id,
                "reason": "Unhandled pipeline error",
                "original_event": str(event),
            })


async def _run_pipeline(event: OrderReceived):
    from app.db import get_order, update_order_status, create_order_event, create_shipment as db_create_shipment
    from app.adapters.erp import create_erp_order
    from app.adapters.inventory import allocate_inventory
    from app.adapters.carrier import create_shipment as carrier_create_shipment

    order_id = event.order_id
    oid = uuid.UUID(order_id)

    # ── Step 1: Validate ─────────────────────────────────────────────────
    order = await get_order(oid)
    if not order:
        logger.error("Order %s not found in DB", order_id)
        await order_exception_topic.send(value={
            "order_id": order_id, "reason": "Order not found in DB",
        })
        return

    if order.status not in ("received",):
        logger.info("Order %s already past 'received' (status=%s), skipping", order_id, order.status)
        return

    if not event.items:
        logger.warning("Order %s has no items — marking exception", order_id)
        await update_order_status(oid, "exception")
        await order_exception_topic.send(value={
            "order_id": order_id, "reason": "No items in order",
        })
        return

    await update_order_status(oid, "validated")
    await order_validated_topic.send(value={
        "order_id": order_id, "external_order_id": event.external_order_id,
    })
    logger.info("Order %s validated", order_id)

    # ── Step 2: ERP sync ─────────────────────────────────────────────────
    erp_result = await create_erp_order(order_id, event.external_order_id, event.items)
    if not erp_result.success:
        await update_order_status(oid, "exception")
        await order_exception_topic.send(value={
            "order_id": order_id, "reason": erp_result.error,
        })
        logger.error("ERP sync failed for order %s: %s", order_id, erp_result.error)
        return

    await update_order_status(oid, "erp_synced")
    await create_order_event(oid, "order.erp.created", {"erp_order_id": erp_result.erp_order_id})
    await order_erp_created_topic.send(value={
        "order_id": order_id, "erp_order_id": erp_result.erp_order_id,
    })
    logger.info("Order %s synced to ERP as %s", order_id, erp_result.erp_order_id)

    # ── Step 3: Inventory allocation ─────────────────────────────────────
    reservations = await allocate_inventory(order_id, event.items)
    await update_order_status(oid, "allocated")
    await order_allocated_topic.send(value={
        "order_id": order_id,
        "reservations": [{"sku": r.sku, "quantity": r.quantity, "id": r.reservation_id} for r in reservations],
    })
    logger.info("Order %s inventory allocated (%d reservations)", order_id, len(reservations))

    # ── Step 4: Shipment creation ────────────────────────────────────────
    carrier_result = await carrier_create_shipment(order_id, event.items)
    shipment = await db_create_shipment(
        order_id=oid,
        carrier=carrier_result.carrier,
        tracking_number=carrier_result.tracking_number,
        label_url=carrier_result.label_url,
    )

    await update_order_status(oid, "shipped")
    await shipment_created_topic.send(value={
        "order_id": order_id,
        "shipment_id": str(shipment.id),
        "carrier": carrier_result.carrier,
        "tracking_number": carrier_result.tracking_number,
    })
    logger.info("Order %s shipped — shipment %s via %s", order_id, shipment.id, carrier_result.carrier)
