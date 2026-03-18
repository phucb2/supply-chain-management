"""
Full scenario simulation — exercises every implemented flow end-to-end.
Run against a live Docker Compose stack:  docker exec api python /app/simulate.py
"""

import json
import sys
import time
import uuid

import asyncio
import asyncpg
import httpx

BASE = "http://localhost:8000"
DB_DSN = "postgresql://supplychain:supplychain_secret@postgresql:5432/supplychain"
TS = str(int(time.time()))

results: list[tuple[str, bool, str]] = []


def report(name: str, passed: bool, detail: str = ""):
    tag = "\033[92mPASS\033[0m" if passed else "\033[91mFAIL\033[0m"
    results.append((name, passed, detail))
    msg = f"  [{tag}] {name}"
    if detail:
        msg += f"  — {detail}"
    print(msg)


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def query_db(sql: str, *args):
    conn = await asyncpg.connect(DB_DSN)
    rows = await conn.fetch(sql, *args)
    await conn.close()
    return rows


def poll_status(order_id: str, target: str, max_wait: int = 60) -> str:
    deadline = time.time() + max_wait
    status = ""
    while time.time() < deadline:
        r = httpx.get(f"{BASE}/orders/{order_id}")
        status = r.json()["status"]
        if status == target or status == "exception":
            return status
        time.sleep(1)
    return status


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 1 — Happy-path order lifecycle
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 1: Happy-path order lifecycle")

order_payload = {
    "external_order_id": f"SIM-HAPPY-{TS}",
    "channel": "shopify",
    "customer_name": "Happy Path User",
    "customer_email": "happy@test.com",
    "shipping_address": "1 Success Blvd, Testville",
    "items": [
        {"sku": "WIDGET-A", "product_name": "Widget Alpha", "quantity": 2, "unit_price": 12.99},
        {"sku": "WIDGET-B", "product_name": "Widget Beta", "quantity": 1, "unit_price": 24.50},
    ],
}

print("\n  Creating order...")
r = httpx.post(f"{BASE}/orders/import", json=order_payload)
report("1.1  POST /orders/import → 201", r.status_code == 201, f"status={r.status_code}")
happy_order = r.json()
happy_id = happy_order["id"]
report("1.2  Order status is 'received'", happy_order["status"] == "received", happy_order["status"])

print("\n  Waiting for pipeline (received → shipped)...")
final = poll_status(happy_id, "shipped")
report("1.3  Pipeline completes to 'shipped'", final == "shipped", f"final={final}")

print("\n  Verifying DB audit trail...")
events = asyncio.run(query_db(
    "SELECT event_type FROM order_events WHERE order_id = $1 ORDER BY created_at",
    uuid.UUID(happy_id),
))
event_types = [e["event_type"] for e in events]
print(f"       Events: {event_types}")
report(
    "1.4  Audit trail has expected events",
    "order.received" in event_types and "order.shipped" in event_types,
    f"{len(event_types)} events",
)

print("\n  Verifying inventory reservations...")
reservations = asyncio.run(query_db(
    "SELECT sku, quantity, status FROM inventory_reservations WHERE order_id = $1",
    uuid.UUID(happy_id),
))
report("1.5  Inventory reservations created", len(reservations) == 2, f"{len(reservations)} rows")
for res in reservations:
    print(f"       {res['sku']}: qty={res['quantity']} status={res['status']}")

print("\n  Verifying shipment was created...")
shipments = asyncio.run(query_db(
    "SELECT id, carrier, tracking_number, status FROM shipments WHERE order_id = $1",
    uuid.UUID(happy_id),
))
report("1.6  Shipment exists in DB", len(shipments) == 1, f"carrier={shipments[0]['carrier']}")
happy_shipment_id = str(shipments[0]["id"])
print(f"       Shipment: {happy_shipment_id}")
print(f"       Carrier:  {shipments[0]['carrier']}")
print(f"       Tracking: {shipments[0]['tracking_number']}")


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 2 — Duplicate order rejection
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 2: Duplicate order rejection")

print("\n  Re-submitting same external_order_id...")
r = httpx.post(f"{BASE}/orders/import", json=order_payload)
report("2.1  Duplicate returns 409", r.status_code == 409, r.json().get("detail", ""))

count = asyncio.run(query_db(
    "SELECT count(*) as c FROM orders WHERE external_order_id = $1",
    order_payload["external_order_id"],
))
report("2.2  Only one row in DB", count[0]["c"] == 1, f"count={count[0]['c']}")


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 3 — Order cancellation
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 3: Order cancellation")

cancel_payload = {
    "external_order_id": f"SIM-CANCEL-{TS}",
    "channel": "manual",
    "customer_name": "Cancel Me",
    "shipping_address": "99 Void Lane",
    "items": [{"sku": "CANCEL-1", "product_name": "Doomed Widget", "quantity": 1, "unit_price": 5.00}],
}

print("\n  Creating order to cancel...")
r = httpx.post(f"{BASE}/orders/import", json=cancel_payload)
cancel_id = r.json()["id"]
report("3.1  Order created", r.status_code == 201)

print("  Cancelling immediately (before pipeline can finish)...")
r = httpx.post(f"{BASE}/orders/{cancel_id}/cancel")
report("3.2  Cancel returns 200", r.status_code == 200)
report("3.3  Status is 'cancelled'", r.json()["status"] == "cancelled", r.json()["status"])

cancel_events = asyncio.run(query_db(
    "SELECT event_type FROM order_events WHERE order_id = $1 ORDER BY created_at",
    uuid.UUID(cancel_id),
))
cancel_types = [e["event_type"] for e in cancel_events]
report("3.4  'order.cancelled' event recorded", "order.cancelled" in cancel_types, str(cancel_types))


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 4 — Cannot cancel shipped order
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 4: Cannot cancel shipped/delivered order")

print(f"\n  Attempting to cancel shipped order {happy_id}...")
r = httpx.post(f"{BASE}/orders/{happy_id}/cancel")
report("4.1  Cancel shipped order returns 409", r.status_code == 409, r.json().get("detail", ""))


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 5 — Shipment tracking updates
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 5: Shipment tracking (in_transit → out_for_delivery → delivered)")

print(f"\n  Using shipment {happy_shipment_id}...")

r = httpx.get(f"{BASE}/shipments/{happy_shipment_id}")
report("5.1  GET /shipments/:id → 200", r.status_code == 200)

print("  Pushing status: picked_up...")
r = httpx.post(f"{BASE}/shipments/{happy_shipment_id}/status", json={
    "status": "picked_up", "location": "Warehouse Floor 3",
})
report("5.2  picked_up → 202", r.status_code == 202)
time.sleep(2)

print("  Pushing status: in_transit...")
r = httpx.post(f"{BASE}/shipments/{happy_shipment_id}/status", json={
    "status": "in_transit", "location": "Highway I-95, Mile 42",
})
report("5.3  in_transit → 202", r.status_code == 202)
time.sleep(2)

print("  Pushing status: out_for_delivery...")
r = httpx.post(f"{BASE}/shipments/{happy_shipment_id}/status", json={
    "status": "out_for_delivery", "location": "Local depot, Testville",
})
report("5.4  out_for_delivery → 202", r.status_code == 202)
time.sleep(2)

print("  Pushing status: delivered...")
r = httpx.post(f"{BASE}/shipments/{happy_shipment_id}/status", json={
    "status": "delivered", "location": "Front door, 1 Success Blvd",
})
report("5.5  delivered → 202", r.status_code == 202)
time.sleep(3)

print("\n  Verifying order transitioned to 'delivered'...")
r = httpx.get(f"{BASE}/orders/{happy_id}")
report("5.6  Order status is 'delivered'", r.json()["status"] == "delivered", r.json()["status"])

print("\n  Fetching tracking history...")
r = httpx.get(f"{BASE}/shipments/{happy_shipment_id}/tracking")
report("5.7  GET /shipments/:id/tracking → 200", r.status_code == 200)
tracking = r.json()
report("5.8  Multiple tracking events recorded", len(tracking) >= 4, f"{len(tracking)} events")
for ev in tracking:
    loc = ev.get("payload", {}).get("location", "—")
    st = ev.get("payload", {}).get("status", "—")
    print(f"       {ev['event_type']}: status={st}  location={loc}")


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 6 — Read endpoints & filtering
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 6: Read endpoints & filtering")

print("\n  GET /orders/ (list all)...")
r = httpx.get(f"{BASE}/orders/")
report("6.1  List orders → 200", r.status_code == 200)
report("6.2  Returns non-empty list", len(r.json()) > 0, f"{len(r.json())} orders")

print("  GET /orders/?status=cancelled ...")
r = httpx.get(f"{BASE}/orders/", params={"status": "cancelled"})
report("6.3  Filter by status works", r.status_code == 200 and all(o["status"] == "cancelled" for o in r.json()),
       f"{len(r.json())} cancelled")

print("  GET /orders/?channel=shopify ...")
r = httpx.get(f"{BASE}/orders/", params={"channel": "shopify"})
report("6.4  Filter by channel works", r.status_code == 200, f"{len(r.json())} shopify orders")

print(f"  GET /orders/{happy_id} ...")
r = httpx.get(f"{BASE}/orders/{happy_id}")
report("6.5  Get single order → 200", r.status_code == 200)

print("  GET /orders/<invalid-uuid> ...")
r = httpx.get(f"{BASE}/orders/00000000-0000-0000-0000-000000000000")
report("6.6  Missing order → 404", r.status_code == 404)

print(f"  GET /shipments/{happy_shipment_id} ...")
r = httpx.get(f"{BASE}/shipments/{happy_shipment_id}")
report("6.7  Get shipment → 200", r.status_code == 200)

print("  GET /shipments/<invalid-uuid> ...")
r = httpx.get(f"{BASE}/shipments/00000000-0000-0000-0000-000000000000")
report("6.8  Missing shipment → 404", r.status_code == 404)


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 7 — Webhook subscriptions
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 7: Webhook subscriptions")

print("\n  Creating subscription...")
r = httpx.post(f"{BASE}/webhooks/subscriptions", json={
    "url": "https://hooks.example.com/supply-chain",
    "events": ["shipment.status-updated", "order.shipped"],
    "secret": "my-hmac-secret",
})
report("7.1  POST /webhooks/subscriptions → 201", r.status_code == 201)
sub = r.json()
print(f"       ID:     {sub['id']}")
print(f"       URL:    {sub['url']}")
print(f"       Events: {sub['events']}")

print("\n  Listing subscriptions...")
r = httpx.get(f"{BASE}/webhooks/subscriptions")
report("7.2  GET /webhooks/subscriptions → 200", r.status_code == 200)
report("7.3  At least 1 subscription", len(r.json()) >= 1, f"{len(r.json())} subs")


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 8 — Inbound webhook
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 8: Inbound webhook receiver")

print("\n  Sending inbound carrier webhook...")
r = httpx.post(f"{BASE}/webhooks/inbound", json={
    "event_type": "shipment.status-updated",
    "reference_id": happy_shipment_id,
    "status": "exception",
    "notes": "Package damaged in transit",
})
report("8.1  POST /webhooks/inbound → 200", r.status_code == 200)


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 9 — Warehouse / driver endpoints
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 9: Warehouse & driver management")

print("\n  POST /warehouse/goods-in ...")
r = httpx.post(f"{BASE}/warehouse/goods-in", json={
    "sku": "RAW-MATERIAL-1", "quantity": 500, "reference_number": "PO-2026-001",
})
report("9.1  Goods-in accepted", r.status_code == 202)

print("  POST /warehouse/goods-out ...")
r = httpx.post(f"{BASE}/warehouse/goods-out", json={
    "sku": "RAW-MATERIAL-1", "quantity": 100, "reference_number": "SO-2026-001",
})
report("9.2  Goods-out accepted", r.status_code == 202)

print("  GET /warehouse/inventory ...")
r = httpx.get(f"{BASE}/warehouse/inventory")
report("9.3  Inventory list → 200", r.status_code == 200)
for item in r.json():
    print(f"       {item['sku']}: qty={item['quantity']}")

print("\n  POST /warehouse/drivers ...")
r = httpx.post(f"{BASE}/warehouse/drivers", json={
    "name": "John Trucker", "phone": "+1-555-0199",
    "vendor": "FastFreight Inc.", "vehicle_plate": "ABC-1234",
})
report("9.4  Driver created → 201", r.status_code == 201)
driver_id = r.json()["id"]
print(f"       Driver ID: {driver_id}")

print(f"  DELETE /warehouse/drivers/{driver_id} ...")
r = httpx.delete(f"{BASE}/warehouse/drivers/{driver_id}")
report("9.5  Driver soft-deleted", r.status_code == 200)


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 10 — Multiple orders pipeline throughput
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 10: Batch throughput — 5 orders")

batch_ids = []
print("\n  Submitting 5 orders...")
for i in range(5):
    payload = {
        "external_order_id": f"SIM-BATCH-{TS}-{i}",
        "channel": "batch-test",
        "customer_name": f"Batch User {i}",
        "shipping_address": f"{i}00 Batch Street",
        "items": [{"sku": f"BATCH-{i}", "product_name": f"Batch Item {i}", "quantity": i + 1, "unit_price": 10.0}],
    }
    r = httpx.post(f"{BASE}/orders/import", json=payload)
    batch_ids.append(r.json()["id"])
    print(f"       Order {i}: {r.json()['id']}")

print("\n  Waiting for all to reach 'shipped' or 'exception'...")
start = time.time()
final_statuses = {}
for oid in batch_ids:
    st = poll_status(oid, "shipped", max_wait=60)
    final_statuses[oid] = st
elapsed = time.time() - start

shipped = sum(1 for s in final_statuses.values() if s == "shipped")
exceptions = sum(1 for s in final_statuses.values() if s == "exception")
print(f"       Shipped: {shipped}  Exceptions: {exceptions}  Time: {elapsed:.1f}s")
report(
    "10.1 All orders processed",
    shipped + exceptions == 5,
    f"{shipped} shipped, {exceptions} exceptions in {elapsed:.1f}s",
)
# ERP mock has 5% failure rate, so exceptions are acceptable
report(
    "10.2 Majority shipped (ERP mock ~95%)",
    shipped >= 4,
    f"{shipped}/5 shipped",
)


# ─────────────────────────────────────────────────────────────────────────────
#  Summary
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  SUMMARY")
print(f"{'='*60}")

passed = sum(1 for _, p, _ in results if p)
failed = sum(1 for _, p, _ in results if not p)
total = len(results)

for name, ok, detail in results:
    if not ok:
        print(f"  \033[91m✗ {name}\033[0m  {detail}")

print(f"\n  \033[{'92' if failed == 0 else '91'}m{passed}/{total} passed, {failed} failed\033[0m\n")

sys.exit(0 if failed == 0 else 1)
