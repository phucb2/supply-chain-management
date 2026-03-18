"""Mock inventory allocation adapter — reserves stock for order items."""

import uuid as _uuid

import structlog

from app.db import create_inventory_reservation

logger = structlog.get_logger()


class Reservation:
    def __init__(self, reservation_id: str, sku: str, quantity: int):
        self.reservation_id = reservation_id
        self.sku = sku
        self.quantity = quantity


async def allocate_inventory(order_id: str, items: list[dict]) -> list[Reservation]:
    """Reserve inventory for each order item. Currently always succeeds."""
    reservations = []
    oid = _uuid.UUID(order_id)

    for item in items:
        db_res = await create_inventory_reservation(
            order_id=oid,
            sku=item["sku"],
            quantity=item["quantity"],
        )
        reservations.append(Reservation(
            reservation_id=str(db_res.id),
            sku=item["sku"],
            quantity=item["quantity"],
        ))
        logger.info("inventory_reserved", order_id=order_id, sku=item["sku"], quantity=item["quantity"])

    return reservations
