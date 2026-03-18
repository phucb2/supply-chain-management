"""Integration tests — shipment endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_get_shipment_not_found(client):
    resp = await client.get("/shipments/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_shipment_status_not_found(client):
    resp = await client.post(
        "/shipments/00000000-0000-0000-0000-000000000000/status",
        json={"status": "in_transit", "location": "Warehouse A"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_tracking_not_found(client):
    resp = await client.get("/shipments/00000000-0000-0000-0000-000000000000/tracking")
    assert resp.status_code == 404
