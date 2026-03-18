"""Mock ERP adapter — simulates order creation in an external ERP system."""

import asyncio
import random
import uuid

import structlog

logger = structlog.get_logger()

SUCCESS_RATE = 0.95
MIN_LATENCY_MS = 200
MAX_LATENCY_MS = 500


class ERPResponse:
    def __init__(self, success: bool, erp_order_id: str | None = None, error: str | None = None):
        self.success = success
        self.erp_order_id = erp_order_id
        self.error = error


async def create_erp_order(order_id: str, external_order_id: str, items: list[dict]) -> ERPResponse:
    """Simulate ERP order creation with random latency and occasional failures."""
    latency = random.randint(MIN_LATENCY_MS, MAX_LATENCY_MS) / 1000
    await asyncio.sleep(latency)

    if random.random() <= SUCCESS_RATE:
        erp_order_id = f"ERP-{uuid.uuid4().hex[:8].upper()}"
        logger.info("erp_order_created", order_id=order_id, erp_order_id=erp_order_id, latency_ms=round(latency * 1000))
        return ERPResponse(success=True, erp_order_id=erp_order_id)
    else:
        logger.warning("erp_order_failed", order_id=order_id, reason="simulated failure")
        return ERPResponse(success=False, error="ERP system unavailable (simulated failure)")
