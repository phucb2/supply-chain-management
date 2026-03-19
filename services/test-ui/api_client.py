"""
Thin HTTP wrapper around the supply-chain FastAPI backend.
All functions accept a `base` URL and return (status_code, json_body) tuples.
"""

from __future__ import annotations

import httpx

TIMEOUT = 15


def _url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}{path}"


def _req(method: str, base: str, path: str, **kwargs) -> tuple[int, dict | list | str]:
    try:
        r = getattr(httpx, method)(_url(base, path), timeout=TIMEOUT, **kwargs)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code, body
    except httpx.ConnectError:
        return 0, {"detail": f"Connection refused — is the API running at {base}?"}
    except httpx.TimeoutException:
        return 0, {"detail": "Request timed out"}


# ── Orders ────────────────────────────────────────────────────────────────────

def create_order(base: str, payload: dict) -> tuple[int, dict]:
    return _req("post", base, "/orders/import", json=payload)


def get_order(base: str, order_id: str) -> tuple[int, dict]:
    return _req("get", base, f"/orders/{order_id}")


def list_orders(base: str, status: str | None = None, channel: str | None = None,
                skip: int = 0, limit: int = 50) -> tuple[int, list]:
    params: dict = {"skip": skip, "limit": limit}
    if status:
        params["status"] = status
    if channel:
        params["channel"] = channel
    return _req("get", base, "/orders/", params=params)


def cancel_order(base: str, order_id: str) -> tuple[int, dict]:
    return _req("post", base, f"/orders/{order_id}/cancel")


# ── Shipments ─────────────────────────────────────────────────────────────────

def get_shipment(base: str, shipment_id: str) -> tuple[int, dict]:
    return _req("get", base, f"/shipments/{shipment_id}")


def get_tracking(base: str, shipment_id: str) -> tuple[int, list]:
    return _req("get", base, f"/shipments/{shipment_id}/tracking")


def push_shipment_status(base: str, shipment_id: str, status: str,
                         location: str | None = None) -> tuple[int, dict]:
    body: dict = {"status": status}
    if location:
        body["location"] = location
    return _req("post", base, f"/shipments/{shipment_id}/status", json=body)


# ── Warehouse ─────────────────────────────────────────────────────────────────

def goods_in(base: str, sku: str, quantity: int,
             reference: str | None = None) -> tuple[int, dict]:
    body: dict = {"sku": sku, "quantity": quantity}
    if reference:
        body["reference_number"] = reference
    return _req("post", base, "/warehouse/goods-in", json=body)


def goods_out(base: str, sku: str, quantity: int,
              reference: str | None = None) -> tuple[int, dict]:
    body: dict = {"sku": sku, "quantity": quantity}
    if reference:
        body["reference_number"] = reference
    return _req("post", base, "/warehouse/goods-out", json=body)


def list_inventory(base: str) -> tuple[int, list]:
    return _req("get", base, "/warehouse/inventory")


def create_driver(base: str, name: str, phone: str | None = None,
                  vendor: str | None = None, plate: str | None = None) -> tuple[int, dict]:
    body: dict = {"name": name}
    if phone:
        body["phone"] = phone
    if vendor:
        body["vendor"] = vendor
    if plate:
        body["vehicle_plate"] = plate
    return _req("post", base, "/warehouse/drivers", json=body)


def delete_driver(base: str, driver_id: str) -> tuple[int, dict]:
    return _req("delete", base, f"/warehouse/drivers/{driver_id}")


# ── Webhooks ──────────────────────────────────────────────────────────────────

def create_subscription(base: str, url: str, events: list[str],
                        secret: str | None = None) -> tuple[int, dict]:
    body: dict = {"url": url, "events": events}
    if secret:
        body["secret"] = secret
    return _req("post", base, "/webhooks/subscriptions", json=body)


def list_subscriptions(base: str) -> tuple[int, list]:
    return _req("get", base, "/webhooks/subscriptions")


def send_inbound_webhook(base: str, payload: dict) -> tuple[int, dict]:
    return _req("post", base, "/webhooks/inbound", json=payload)


# ── Health ────────────────────────────────────────────────────────────────────

def health_check(base: str) -> tuple[int, dict]:
    return _req("get", base, "/health")
