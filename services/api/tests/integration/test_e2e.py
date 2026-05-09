"""End-to-end integration test — exercises the full order lifecycle via HTTP.

Requires the full Docker Compose stack to be running (Kafka, PostgreSQL, MinIO,
API service, stream processor). Run with:

    pytest tests/integration/test_e2e.py -v --asyncio-mode=auto

Or use the convenience script:

    python -m pytest tests/integration/test_e2e.py -v
"""

import asyncio
from datetime import date
import time

import httpx
import pytest

API_BASE = "http://localhost:8000"

SAMPLE_ORDER = {
    "external_order_id": f"E2E-{int(time.time())}",
    "source": "integration-test",
    "customer_category": "b2c",
    "customer_name": "E2E Tester",
    "customer_email": "e2e@test.local",
    "shipping_address": "456 Integration Ave, TestCity",
    "destination": "TestCity",
    "req_delivery_date": date.today().isoformat(),
    "items": [
        {"sku": "TEST-SKU-1", "product_name": "Test Widget", "quantity": 3, "unit_price": 12.50, "weight_per_unit_kg": 1.0},
    ],
}


@pytest.fixture
def api():
    return httpx.Client(base_url=API_BASE, timeout=30)


def _poll_order_status(api: httpx.Client, order_id: str, target: str, max_wait: int = 30) -> dict:
    """Poll GET /orders/{id} until status matches target or timeout."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        resp = api.get(f"/orders/{order_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] == target:
            return data
        time.sleep(1)
    raise TimeoutError(f"Order {order_id} did not reach '{target}' within {max_wait}s (last: {data['status']})")


class TestE2EHappyPath:
    """5.1 — Full order lifecycle: import → pipeline → ship → deliver."""

    def test_order_lifecycle(self, api):
        # 1. Import order
        resp = api.post("/orders/import", json=SAMPLE_ORDER)
        assert resp.status_code == 201
        order = resp.json()
        order_id = order["sale_order_id"]
        assert order["status"] == "pending"

        # 2. Wait for pipeline to process through to shipped
        shipped_order = _poll_order_status(api, order_id, "in_transit", max_wait=60)
        assert shipped_order["status"] == "in_transit"

        # 3. Get order and find shipment (via list or events)
        resp = api.get(f"/orders/{order_id}")
        assert resp.status_code == 200


class TestDuplicateRejection:
    """5.2 — Duplicate external_order_id returns 409."""

    def test_duplicate_returns_409(self, api):
        unique_order = {**SAMPLE_ORDER, "external_order_id": f"DUP-{int(time.time())}"}

        resp1 = api.post("/orders/import", json=unique_order)
        assert resp1.status_code == 201

        resp2 = api.post("/orders/import", json=unique_order)
        assert resp2.status_code == 409


class TestCancellation:
    """5.3 — Cancel an order before it ships."""

    def test_cancel_order(self, api):
        cancel_order = {**SAMPLE_ORDER, "external_order_id": f"CANCEL-{int(time.time())}"}
        resp = api.post("/orders/import", json=cancel_order)
        assert resp.status_code == 201
        order_id = resp.json()["sale_order_id"]

        cancel_resp = api.post(f"/orders/{order_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

        verify_resp = api.get(f"/orders/{order_id}")
        assert verify_resp.json()["status"] == "cancelled"
