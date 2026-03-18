"""Integration tests — webhook endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_create_subscription(client):
    resp = await client.post("/webhooks/subscriptions", json={
        "url": "https://example.com/hook",
        "events": ["shipment.status-updated"],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["url"] == "https://example.com/hook"


@pytest.mark.asyncio
async def test_list_subscriptions(client):
    resp = await client.get("/webhooks/subscriptions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_inbound_webhook(client):
    resp = await client.post("/webhooks/inbound", json={
        "event_type": "shipment.status-updated",
        "reference_id": "test-ref-001",
        "status": "delivered",
    })
    assert resp.status_code == 200
