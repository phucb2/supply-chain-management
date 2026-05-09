"""
Test scenarios for E2E supply-chain validation.
Mirrors scripts/simulate.py but structured as callable functions for the UI.
"""

from __future__ import annotations

from datetime import date
import time
from dataclasses import dataclass, field

import httpx

POLL_INTERVAL = 1
DEFAULT_TIMEOUT = 60


@dataclass
class TestResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ScenarioContext:
    """Shared state passed between dependent scenarios."""

    happy_order_id: str = ""
    happy_shipment_id: str = ""
    happy_order_payload: dict = field(default_factory=dict)
    cancel_order_id: str = ""
    ts: str = field(default_factory=lambda: str(int(time.time())))


SCENARIOS: dict[int, dict] = {
    1: {
        "title": "Happy-path order lifecycle",
        "description": "Create an order and wait for the pipeline to move it to 'in_transit'.",
        "depends_on": [],
    },
    2: {
        "title": "Duplicate order rejection",
        "description": "Re-submit the same external_order_id and expect a 409 conflict.",
        "depends_on": [1],
    },
    3: {
        "title": "Order cancellation",
        "description": "Create an order and immediately cancel it.",
        "depends_on": [],
    },
    4: {
        "title": "Cannot cancel in-transit order",
        "description": "Attempt to cancel an in-transit order and expect a 409 conflict.",
        "depends_on": [1],
    },
    5: {
        "title": "Shipment tracking updates",
        "description": "Push tracking statuses (picked_up → in_transit → out_for_delivery → delivered).",
        "depends_on": [1],
    },
    6: {
        "title": "Read endpoints & filtering",
        "description": "Verify list, filter, single-get, and 404 behaviour for orders and shipments.",
        "depends_on": [1],
    },
    7: {
        "title": "Webhook subscriptions",
        "description": "Create and list webhook subscriptions.",
        "depends_on": [],
    },
    8: {
        "title": "Inbound webhook receiver",
        "description": "Send an inbound carrier webhook event.",
        "depends_on": [1],
    },
    9: {
        "title": "Warehouse & driver management",
        "description": "Test goods-in, goods-out, inventory listing, and driver CRUD.",
        "depends_on": [],
    },
    10: {
        "title": "Batch throughput (5 orders)",
        "description": "Submit 5 orders in parallel and wait for the pipeline to process them all.",
        "depends_on": [],
    },
}


def _poll_status(
    base: str,
    order_id: str,
    target: str,
    max_wait: int = DEFAULT_TIMEOUT,
    on_poll=None,
) -> str:
    deadline = time.time() + max_wait
    status = ""
    while time.time() < deadline:
        r = httpx.get(f"{base}/orders/{order_id}", timeout=10)
        status = r.json()["status"]
        if on_poll:
            on_poll(status)
        if status == target or status == "exception":
            return status
        time.sleep(POLL_INTERVAL)
    return status


def _safe_json(r: httpx.Response) -> dict:
    try:
        return r.json()
    except Exception:
        return {}


def run_scenario(num: int, base: str, ctx: ScenarioContext, on_poll=None) -> list[TestResult]:
    runners = {
        1: _scenario_1,
        2: _scenario_2,
        3: _scenario_3,
        4: _scenario_4,
        5: _scenario_5,
        6: _scenario_6,
        7: _scenario_7,
        8: _scenario_8,
        9: _scenario_9,
        10: _scenario_10,
    }
    return runners[num](base, ctx, on_poll)


# ---------------------------------------------------------------------------
#  Scenario 1 — Happy-path order lifecycle
# ---------------------------------------------------------------------------

def _scenario_1(base: str, ctx: ScenarioContext, on_poll=None) -> list[TestResult]:
    results: list[TestResult] = []

    payload = {
        "external_order_id": f"UI-HAPPY-{ctx.ts}",
        "source": "shopify",
        "customer_category": "b2c",
        "customer_name": "Happy Path User",
        "customer_email": "happy@test.com",
        "shipping_address": "1 Success Blvd, Testville",
        "destination": "Testville",
        "req_delivery_date": date.today().isoformat(),
        "items": [
            {"sku": "WIDGET-A", "product_name": "Widget Alpha", "quantity": 2, "unit_price": 12.99, "weight_per_unit_kg": 1.0},
            {"sku": "WIDGET-B", "product_name": "Widget Beta", "quantity": 1, "unit_price": 24.50, "weight_per_unit_kg": 1.0},
        ],
    }
    ctx.happy_order_payload = payload

    r = httpx.post(f"{base}/orders/import", json=payload, timeout=10)
    results.append(TestResult("1.1 POST /orders/import -> 201", r.status_code == 201, f"status={r.status_code}"))

    if r.status_code != 201:
        return results

    order = r.json()
    ctx.happy_order_id = order["sale_order_id"]
    ctx.happy_shipment_id = order["delivery_order_id"]
    results.append(TestResult("1.2 Order status is 'pending'", order["status"] == "pending", order["status"]))

    final = _poll_status(base, ctx.happy_order_id, "in_transit", on_poll=on_poll)
    results.append(TestResult("1.3 Pipeline completes to 'in_transit'", final == "in_transit", f"final={final}"))

    r = httpx.get(f"{base}/orders/{ctx.happy_order_id}", timeout=10)
    if r.status_code == 200:
        order_data = r.json()
        results.append(TestResult(
            "1.4 Order retrievable after pipeline",
            order_data["status"] in ("in_transit", "delivered"),
            f"status={order_data['status']}",
        ))

    inv = httpx.get(f"{base}/warehouse/inventory", timeout=10)
    if inv.status_code == 200:
        skus = [item["sku"] for item in inv.json()]
        has_widgets = "WIDGET-A" in skus or "WIDGET-B" in skus
        results.append(TestResult("1.5 Inventory reservations visible", has_widgets, f"skus={skus}"))

    return results


# ---------------------------------------------------------------------------
#  Scenario 2 — Duplicate order rejection
# ---------------------------------------------------------------------------

def _scenario_2(base: str, ctx: ScenarioContext, _on_poll=None) -> list[TestResult]:
    results: list[TestResult] = []

    if not ctx.happy_order_payload:
        results.append(TestResult("2.0 Prerequisite: scenario 1 must run first", False, "no payload"))
        return results

    r = httpx.post(f"{base}/orders/import", json=ctx.happy_order_payload, timeout=10)
    body = _safe_json(r)
    results.append(TestResult("2.1 Duplicate returns 409", r.status_code == 409, body.get("detail", "")))

    r2 = httpx.get(f"{base}/orders/", params={"channel": "shopify"}, timeout=10)
    if r2.status_code == 200:
        matching = [
            o for o in r2.json()
            if o.get("external_order_id") == ctx.happy_order_payload["external_order_id"]
        ]
        results.append(TestResult("2.2 Only one order with that external_id", len(matching) == 1, f"count={len(matching)}"))

    return results


# ---------------------------------------------------------------------------
#  Scenario 3 — Order cancellation
# ---------------------------------------------------------------------------

def _scenario_3(base: str, ctx: ScenarioContext, _on_poll=None) -> list[TestResult]:
    results: list[TestResult] = []

    cancel_payload = {
        "external_order_id": f"UI-CANCEL-{ctx.ts}",
        "source": "manual",
        "customer_category": "b2c",
        "customer_name": "Cancel Me",
        "shipping_address": "99 Void Lane",
        "destination": "Void Lane",
        "req_delivery_date": date.today().isoformat(),
        "items": [{"sku": "CANCEL-1", "product_name": "Doomed Widget", "quantity": 1, "unit_price": 5.00, "weight_per_unit_kg": 1.0}],
    }

    r = httpx.post(f"{base}/orders/import", json=cancel_payload, timeout=10)
    results.append(TestResult("3.1 Order created", r.status_code == 201))
    if r.status_code != 201:
        return results

    cancel_id = r.json()["sale_order_id"]
    ctx.cancel_order_id = cancel_id

    r = httpx.post(f"{base}/orders/{cancel_id}/cancel", timeout=10)
    results.append(TestResult("3.2 Cancel returns 200", r.status_code == 200))

    body = _safe_json(r)
    results.append(TestResult("3.3 Status is 'cancelled'", body.get("status") == "cancelled", body.get("status", "")))

    r2 = httpx.get(f"{base}/orders/{cancel_id}", timeout=10)
    if r2.status_code == 200:
        results.append(TestResult(
            "3.4 GET confirms cancelled status",
            r2.json()["status"] == "cancelled",
            r2.json()["status"],
        ))

    return results


# ---------------------------------------------------------------------------
#  Scenario 4 — Cannot cancel shipped order
# ---------------------------------------------------------------------------

def _scenario_4(base: str, ctx: ScenarioContext, _on_poll=None) -> list[TestResult]:
    results: list[TestResult] = []

    if not ctx.happy_order_id:
        results.append(TestResult("4.0 Prerequisite: scenario 1 must run first", False, "no order_id"))
        return results

    r = httpx.post(f"{base}/orders/{ctx.happy_order_id}/cancel", timeout=10)
    body = _safe_json(r)
    results.append(TestResult("4.1 Cancel shipped order returns 409", r.status_code == 409, body.get("detail", "")))

    return results


# ---------------------------------------------------------------------------
#  Scenario 5 — Shipment tracking updates
# ---------------------------------------------------------------------------

def _scenario_5(base: str, ctx: ScenarioContext, _on_poll=None) -> list[TestResult]:
    results: list[TestResult] = []

    if not ctx.happy_shipment_id:
        results.append(TestResult(
            "5.0 Prerequisite: shipment ID required",
            False,
            "Enter a shipment ID in the sidebar or run scenario 1 first",
        ))
        return results

    sid = ctx.happy_shipment_id

    r = httpx.get(f"{base}/shipments/{sid}", timeout=10)
    results.append(TestResult("5.1 GET /shipments/:id -> 200", r.status_code == 200))
    if r.status_code != 200:
        return results

    tracking_steps = [
        ("picked_up", "Warehouse Floor 3"),
        ("in_transit", "Highway I-95, Mile 42"),
        ("out_for_delivery", "Local depot, Testville"),
        ("delivered", "Front door, 1 Success Blvd"),
    ]

    for i, (status, location) in enumerate(tracking_steps, start=2):
        r = httpx.post(
            f"{base}/shipments/{sid}/status",
            json={"status": status, "location": location},
            timeout=10,
        )
        results.append(TestResult(f"5.{i} {status} -> 202", r.status_code == 202))
        time.sleep(2)

    time.sleep(3)

    if ctx.happy_order_id:
        r = httpx.get(f"{base}/orders/{ctx.happy_order_id}", timeout=10)
        results.append(TestResult(
            "5.6 Order status is 'delivered'",
            r.json().get("status") == "delivered",
            r.json().get("status", ""),
        ))

    r = httpx.get(f"{base}/shipments/{sid}/tracking", timeout=10)
    results.append(TestResult("5.7 GET /shipments/:id/tracking -> 200", r.status_code == 200))
    if r.status_code == 200:
        tracking = r.json()
        results.append(TestResult("5.8 Multiple tracking events recorded", len(tracking) >= 4, f"{len(tracking)} events"))

    return results


# ---------------------------------------------------------------------------
#  Scenario 6 — Read endpoints & filtering
# ---------------------------------------------------------------------------

def _scenario_6(base: str, ctx: ScenarioContext, _on_poll=None) -> list[TestResult]:
    results: list[TestResult] = []

    r = httpx.get(f"{base}/orders/", timeout=10)
    results.append(TestResult("6.1 List orders -> 200", r.status_code == 200))
    if r.status_code == 200:
        results.append(TestResult("6.2 Returns non-empty list", len(r.json()) > 0, f"{len(r.json())} orders"))

    r = httpx.get(f"{base}/orders/", params={"status": "cancelled"}, timeout=10)
    ok = r.status_code == 200 and all(o["status"] == "cancelled" for o in r.json())
    results.append(TestResult("6.3 Filter by status works", ok, f"{len(r.json())} cancelled"))

    r = httpx.get(f"{base}/orders/", params={"channel": "shopify"}, timeout=10)
    results.append(TestResult("6.4 Filter by channel works", r.status_code == 200, f"{len(r.json())} shopify orders"))

    if ctx.happy_order_id:
        r = httpx.get(f"{base}/orders/{ctx.happy_order_id}", timeout=10)
        results.append(TestResult("6.5 Get single order -> 200", r.status_code == 200))

    r = httpx.get(f"{base}/orders/00000000-0000-0000-0000-000000000000", timeout=10)
    results.append(TestResult("6.6 Missing order -> 404", r.status_code == 404))

    if ctx.happy_shipment_id:
        r = httpx.get(f"{base}/shipments/{ctx.happy_shipment_id}", timeout=10)
        results.append(TestResult("6.7 Get shipment -> 200", r.status_code == 200))

    r = httpx.get(f"{base}/shipments/00000000-0000-0000-0000-000000000000", timeout=10)
    results.append(TestResult("6.8 Missing shipment -> 404", r.status_code == 404))

    return results


# ---------------------------------------------------------------------------
#  Scenario 7 — Webhook subscriptions
# ---------------------------------------------------------------------------

def _scenario_7(base: str, _ctx: ScenarioContext, _on_poll=None) -> list[TestResult]:
    results: list[TestResult] = []

    r = httpx.post(f"{base}/webhooks/subscriptions", json={
        "url": "https://hooks.example.com/supply-chain",
        "events": ["shipment.status-updated", "order.shipped"],
        "secret": "my-hmac-secret",
    }, timeout=10)
    results.append(TestResult("7.1 POST /webhooks/subscriptions -> 201", r.status_code == 201))
    if r.status_code == 201:
        sub = r.json()
        results[-1].detail = f"id={sub['id']}"

    r = httpx.get(f"{base}/webhooks/subscriptions", timeout=10)
    results.append(TestResult("7.2 GET /webhooks/subscriptions -> 200", r.status_code == 200))
    if r.status_code == 200:
        results.append(TestResult("7.3 At least 1 subscription", len(r.json()) >= 1, f"{len(r.json())} subs"))

    return results


# ---------------------------------------------------------------------------
#  Scenario 8 — Inbound webhook
# ---------------------------------------------------------------------------

def _scenario_8(base: str, ctx: ScenarioContext, _on_poll=None) -> list[TestResult]:
    results: list[TestResult] = []

    ref_id = ctx.happy_shipment_id or "00000000-0000-0000-0000-000000000000"

    r = httpx.post(f"{base}/webhooks/inbound", json={
        "event_type": "shipment.status-updated",
        "reference_id": ref_id,
        "status": "exception",
        "notes": "Package damaged in transit",
    }, timeout=10)
    results.append(TestResult("8.1 POST /webhooks/inbound -> 200", r.status_code == 200))

    return results


# ---------------------------------------------------------------------------
#  Scenario 9 — Warehouse & driver management
# ---------------------------------------------------------------------------

def _scenario_9(base: str, _ctx: ScenarioContext, _on_poll=None) -> list[TestResult]:
    results: list[TestResult] = []

    r = httpx.post(f"{base}/warehouse/goods-in", json={
        "sku": "RAW-MATERIAL-1", "quantity": 500, "reference_number": "PO-2026-001",
    }, timeout=10)
    results.append(TestResult("9.1 Goods-in accepted", r.status_code == 202))

    r = httpx.post(f"{base}/warehouse/goods-out", json={
        "sku": "RAW-MATERIAL-1", "quantity": 100, "reference_number": "SO-2026-001",
    }, timeout=10)
    results.append(TestResult("9.2 Goods-out accepted", r.status_code == 202))

    r = httpx.get(f"{base}/warehouse/inventory", timeout=10)
    results.append(TestResult("9.3 Inventory list -> 200", r.status_code == 200))
    if r.status_code == 200:
        items = r.json()
        results[-1].detail = ", ".join(f"{i['sku']}={i['quantity']}" for i in items)

    r = httpx.post(f"{base}/warehouse/drivers", json={
        "name": "John Trucker",
        "phone": "+1-555-0199",
        "vendor": "FastFreight Inc.",
        "vehicle_plate": "ABC-1234",
    }, timeout=10)
    results.append(TestResult("9.4 Driver created -> 201", r.status_code == 201))

    if r.status_code == 201:
        driver_id = r.json()["id"]
        results[-1].detail = f"id={driver_id}"

        r = httpx.delete(f"{base}/warehouse/drivers/{driver_id}", timeout=10)
        results.append(TestResult("9.5 Driver soft-deleted", r.status_code == 200))

    return results


# ---------------------------------------------------------------------------
#  Scenario 10 — Batch throughput
# ---------------------------------------------------------------------------

def _scenario_10(base: str, ctx: ScenarioContext, on_poll=None) -> list[TestResult]:
    results: list[TestResult] = []

    batch_ids = []
    for i in range(5):
        payload = {
            "external_order_id": f"UI-BATCH-{ctx.ts}-{i}",
            "source": "batch-test",
            "customer_category": "b2c",
            "customer_name": f"Batch User {i}",
            "shipping_address": f"{i}00 Batch Street",
            "destination": "Batch City",
            "req_delivery_date": date.today().isoformat(),
            "items": [{"sku": f"BATCH-{i}", "product_name": f"Batch Item {i}", "quantity": i + 1, "unit_price": 10.0, "weight_per_unit_kg": 1.0}],
        }
        r = httpx.post(f"{base}/orders/import", json=payload, timeout=10)
        if r.status_code == 201:
            batch_ids.append(r.json()["sale_order_id"])

    start = time.time()
    final_statuses = {}
    for oid in batch_ids:
        st = _poll_status(base, oid, "in_transit", max_wait=DEFAULT_TIMEOUT, on_poll=on_poll)
        final_statuses[oid] = st
    elapsed = time.time() - start

    shipped = sum(1 for s in final_statuses.values() if s == "in_transit")
    exceptions = sum(1 for s in final_statuses.values() if s == "exception")

    results.append(TestResult(
        "10.1 All orders processed",
        shipped + exceptions == 5,
        f"{shipped} shipped, {exceptions} exceptions in {elapsed:.1f}s",
    ))
    results.append(TestResult(
        "10.2 Majority shipped (ERP mock ~95%)",
        shipped >= 4,
        f"{shipped}/5 shipped",
    ))

    return results
