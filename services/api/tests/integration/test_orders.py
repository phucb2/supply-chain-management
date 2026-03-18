"""Integration tests — order endpoints (happy path, duplicates, cancellation)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

SAMPLE_ORDER = {
    "external_order_id": "EXT-001",
    "channel": "shopify",
    "customer_name": "Alice Test",
    "customer_email": "alice@example.com",
    "shipping_address": "123 Test St, City, Country",
    "items": [
        {"sku": "SKU-A", "product_name": "Widget A", "quantity": 2, "unit_price": 9.99},
        {"sku": "SKU-B", "product_name": "Widget B", "quantity": 1, "unit_price": 19.99},
    ],
}


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_import_order_returns_201(client):
    resp = await client.post("/orders/import", json=SAMPLE_ORDER)
    assert resp.status_code == 201
    data = resp.json()
    assert data["external_order_id"] == "EXT-001"
    assert data["status"] == "received"
    assert "id" in data


@pytest.mark.asyncio
async def test_duplicate_order_returns_409(client):
    order = {**SAMPLE_ORDER, "external_order_id": "EXT-DUP-001"}
    resp1 = await client.post("/orders/import", json=order)
    assert resp1.status_code == 201

    resp2 = await client.post("/orders/import", json=order)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_get_order_returns_200(client):
    order = {**SAMPLE_ORDER, "external_order_id": "EXT-GET-001"}
    create_resp = await client.post("/orders/import", json=order)
    order_id = create_resp.json()["id"]

    resp = await client.get(f"/orders/{order_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == order_id


@pytest.mark.asyncio
async def test_get_order_not_found(client):
    resp = await client.get("/orders/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_orders(client):
    resp = await client.get("/orders/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_cancel_order(client):
    order = {**SAMPLE_ORDER, "external_order_id": "EXT-CANCEL-001"}
    create_resp = await client.post("/orders/import", json=order)
    order_id = create_resp.json()["id"]

    resp = await client.post(f"/orders/{order_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_not_found(client):
    resp = await client.post("/orders/00000000-0000-0000-0000-000000000000/cancel")
    assert resp.status_code == 404
