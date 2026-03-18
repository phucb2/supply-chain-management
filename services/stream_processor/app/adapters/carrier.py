"""Mock carrier adapter — simulates shipment label creation."""

import asyncio
import logging
import random
import uuid

logger = logging.getLogger(__name__)

CARRIERS = ["FedEx", "UPS", "DHL", "USPS"]


class ShipmentResult:
    def __init__(self, tracking_number: str, carrier: str, label_url: str):
        self.tracking_number = tracking_number
        self.carrier = carrier
        self.label_url = label_url


async def create_shipment(order_id: str, items: list[dict]) -> ShipmentResult:
    """Simulate carrier shipment creation with mock tracking number and label."""
    await asyncio.sleep(random.randint(100, 300) / 1000)

    carrier = random.choice(CARRIERS)
    tracking_number = f"{carrier[:3].upper()}-{uuid.uuid4().hex[:10].upper()}"
    label_url = f"https://labels.example.com/{tracking_number}.pdf"

    logger.info("Shipment created for order %s: %s via %s", order_id, tracking_number, carrier)

    return ShipmentResult(
        tracking_number=tracking_number,
        carrier=carrier,
        label_url=label_url,
    )
