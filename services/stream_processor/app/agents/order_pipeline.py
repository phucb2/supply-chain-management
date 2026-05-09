"""Order processing pipeline: validate → ERP sync → allocate inventory → create shipment."""

import time
import uuid

import structlog
from opentelemetry import trace

from app.main import app
from app.models import OrderReceived
from observability import (
    orders_exception,
    orders_shipped,
    orders_validated,
    pipeline_duration,
    shipments_created,
)

logger = structlog.get_logger()
tracer = trace.get_tracer(__name__)

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
        with tracer.start_as_current_span(
            "order.pipeline", attributes={"order.id": order_id},
        ):
            logger.info("pipeline_started", order_id=order_id)
            start = time.monotonic()

            try:
                await _run_pipeline(event)
                pipeline_duration.record(
                    (time.monotonic() - start) * 1000,
                    {"channel": event.channel},
                )
            except Exception:
                logger.exception("pipeline_permanent_failure", order_id=order_id)
                orders_exception.add(1, {"channel": event.channel})
                try:
                    from app.db import create_order_event, update_order_status

                    await update_order_status(uuid.UUID(order_id), "exception")
                    await create_order_event(
                        uuid.UUID(order_id),
                        "order.exception",
                        {"reason": "Unhandled pipeline error"},
                    )
                except Exception:
                    logger.exception("status_update_failed", order_id=order_id)

                await dlq_topic.send(value={
                    "order_id": order_id,
                    "reason": "Unhandled pipeline error",
                    "original_event": str(event),
                })


async def _run_pipeline(event: OrderReceived):
    from app.adapters.carrier import create_shipment as carrier_create_shipment
    from app.adapters.erp import create_erp_order
    from app.adapters.inventory import allocate_inventory
    from app.db import (
        create_order_event,
        create_shipment as db_create_shipment,
        get_order,
        update_order_status,
    )

    order_id = event.order_id
    oid = uuid.UUID(order_id)

    # ── Step 1: Validate ─────────────────────────────────────────────────
    with tracer.start_as_current_span("order.validate", attributes={"order.id": order_id}):
        order = await get_order(oid)
        if not order:
            logger.error("order_not_found", order_id=order_id, step="validate")
            await order_exception_topic.send(value={
                "order_id": order_id, "reason": "Order not found in DB",
            })
            return

        if order.status not in ("pending",):
            logger.info("order_skipped", order_id=order_id, status=order.status, step="validate")
            return

        if not event.items:
            logger.warning("order_no_items", order_id=order_id, step="validate")
            await update_order_status(oid, "exception")
            orders_exception.add(1, {"channel": event.channel})
            await order_exception_topic.send(value={
                "order_id": order_id, "reason": "No items in order",
            })
            return

        await update_order_status(oid, "confirmed")
        await order_validated_topic.send(value={
            "order_id": order_id, "external_order_id": event.external_order_id,
        })
        orders_validated.add(1, {"channel": event.channel})
        logger.info("order_validated", order_id=order_id, step="validate")

    # ── Step 2: ERP sync ─────────────────────────────────────────────────
    with tracer.start_as_current_span("order.erp_sync", attributes={"order.id": order_id}):
        erp_result = await create_erp_order(order_id, event.external_order_id, event.items)
        if not erp_result.success:
            await update_order_status(oid, "exception")
            orders_exception.add(1, {"channel": event.channel})
            await order_exception_topic.send(value={
                "order_id": order_id, "reason": erp_result.error,
            })
            logger.error("erp_sync_failed", order_id=order_id, error=erp_result.error, step="erp_sync")
            return

        await update_order_status(oid, "confirmed")
        await create_order_event(oid, "order.erp.created", {"erp_order_id": erp_result.erp_order_id})
        await order_erp_created_topic.send(value={
            "order_id": order_id, "erp_order_id": erp_result.erp_order_id,
        })
        logger.info("erp_synced", order_id=order_id, erp_order_id=erp_result.erp_order_id, step="erp_sync")

    # ── Step 3: Inventory allocation ─────────────────────────────────────
    with tracer.start_as_current_span("order.allocate", attributes={"order.id": order_id}):
        reservations = await allocate_inventory(order_id, event.items)
        await update_order_status(oid, "allocated")
        await order_allocated_topic.send(value={
            "order_id": order_id,
            "reservations": [{"sku": r.sku, "quantity": r.quantity, "id": r.reservation_id} for r in reservations],
        })
        logger.info("inventory_allocated", order_id=order_id, reservation_count=len(reservations), step="allocate")

    # ── Step 4: Shipment creation ────────────────────────────────────────
    with tracer.start_as_current_span("order.ship", attributes={"order.id": order_id}):
        carrier_result = await carrier_create_shipment(order_id, event.items)
        shipment = await db_create_shipment(
            order_id=oid,
            carrier=carrier_result.carrier,
            tracking_number=carrier_result.tracking_number,
            label_url=carrier_result.label_url,
        )

        await update_order_status(oid, "in_transit")
        await shipment_created_topic.send(value={
            "order_id": order_id,
            "delivery_order_id": str(shipment.delivery_order_id),
            "carrier": carrier_result.carrier,
            "tracking_number": carrier_result.tracking_number,
        })
        orders_shipped.add(1, {"channel": event.channel, "carrier": carrier_result.carrier})
        shipments_created.add(1, {"carrier": carrier_result.carrier})
        logger.info(
            "order_shipped",
            order_id=order_id,
            shipment_id=str(shipment.delivery_order_id),
            carrier=carrier_result.carrier,
            step="ship",
        )
