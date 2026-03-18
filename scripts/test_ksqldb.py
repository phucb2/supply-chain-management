"""
ksqlDB integration test — verifies streams and tables capture order events.
Run against a live Docker Compose stack:  docker exec api python /tmp/test_ksqldb.py
Or from host (change BASE / KSQLDB_URL to localhost).
"""

import json
import sys
import time

import httpx

API_BASE = "http://localhost:8000"
KSQLDB_URL = "http://ksqldb-server:8088"
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


def ksql_execute(statement: str) -> dict:
    """Run a ksqlDB statement via REST API (DDL / SHOW / LIST)."""
    r = httpx.post(
        f"{KSQLDB_URL}/ksql",
        json={"ksql": statement, "streamsProperties": {}},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def ksql_query(query: str, earliest: bool = True) -> list[dict]:
    """Run a ksqlDB pull or push query, return rows as dicts."""
    props = {}
    if earliest:
        props["auto.offset.reset"] = "earliest"
    r = httpx.post(
        f"{KSQLDB_URL}/query",
        json={"ksql": query, "streamsProperties": props},
        timeout=30,
    )
    r.raise_for_status()

    lines = [line for line in r.text.strip().split("\n") if line.strip()]
    if not lines:
        return []

    parsed = [json.loads(line) for line in lines]
    header = parsed[0]
    columns = header.get("columnNames", [])
    if not columns:
        return []

    return [
        dict(zip(columns, row))
        for row in parsed[1:]
        if isinstance(row, list)
    ]


# ─────────────────────────────────────────────────────────────────────────────
#  Pre-check: ksqlDB server health
# ─────────────────────────────────────────────────────────────────────────────
section("Pre-check: ksqlDB server health")

print("\n  Checking ksqlDB /info endpoint...")
try:
    r = httpx.get(f"{KSQLDB_URL}/info", timeout=5)
    info = r.json().get("KsqlServerInfo", {})
    report("0.1  ksqlDB server reachable", r.status_code == 200, f"version={info.get('version', '?')}")
except Exception as e:
    report("0.1  ksqlDB server reachable", False, str(e))
    print("\n  Cannot reach ksqlDB — aborting.\n")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 1 — Verify streams exist
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 1: ksqlDB streams exist")

print("\n  SHOW STREAMS...")
resp = ksql_execute("SHOW STREAMS;")
stream_names = [s["name"] for s in resp[0].get("streams", [])]
print(f"       Found: {stream_names}")

expected_streams = [
    "ORDER_RECEIVED", "ORDER_VALIDATED", "ORDER_ERP_CREATED",
    "ORDER_ALLOCATED", "ORDER_EXCEPTION", "ORDER_CANCELLED",
    "SHIPMENT_CREATED", "SHIPMENT_STATUS_UPDATED",
]
for name in expected_streams:
    report(f"1.x  Stream {name}", name in stream_names)


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 2 — Verify tables exist
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 2: ksqlDB materialized tables exist")

print("\n  SHOW TABLES...")
resp = ksql_execute("SHOW TABLES;")
table_names = [t["name"] for t in resp[0].get("tables", [])]
print(f"       Found: {table_names}")

expected_tables = ["ORDERS_BY_CHANNEL", "SHIPMENTS_BY_CARRIER", "EXCEPTIONS_BY_REASON"]
for name in expected_tables:
    report(f"2.x  Table {name}", name in table_names)


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 3 — Create order and verify it appears in ksqlDB stream
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 3: Order flows into ksqlDB stream")

order_payload = {
    "external_order_id": f"KSQL-TEST-{TS}",
    "channel": "ksql-test",
    "customer_name": "KsqlDB Tester",
    "customer_email": "ksql@test.com",
    "shipping_address": "42 Stream Ave, Kafkaville",
    "items": [
        {"sku": "KSQL-ITEM-1", "product_name": "Stream Widget", "quantity": 3, "unit_price": 19.99},
        {"sku": "KSQL-ITEM-2", "product_name": "Table Widget", "quantity": 1, "unit_price": 49.99},
    ],
}

print("\n  Creating order via API...")
r = httpx.post(f"{API_BASE}/orders/import", json=order_payload)
report("3.1  POST /orders/import → 201", r.status_code == 201, f"status={r.status_code}")
order = r.json()
order_id = order["id"]
print(f"       Order ID: {order_id}")

print("\n  Waiting for event to reach Kafka...")
time.sleep(3)

print("  Querying ORDER_RECEIVED stream...")
rows = ksql_query(
    f"SELECT ORDER_ID, CHANNEL, CUSTOMER_NAME FROM ORDER_RECEIVED "
    f"WHERE CHANNEL = 'ksql-test' EMIT CHANGES LIMIT 1;"
)
report("3.2  Order visible in ORDER_RECEIVED", len(rows) >= 1, f"{len(rows)} row(s)")
if rows:
    print(f"       order_id:  {rows[0].get('ORDER_ID')}")
    print(f"       channel:   {rows[0].get('CHANNEL')}")
    print(f"       customer:  {rows[0].get('CUSTOMER_NAME')}")


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 4 — Wait for pipeline, then check downstream streams
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 4: Pipeline events in ksqlDB")

print("\n  Waiting for pipeline to complete (up to 30s)...")
deadline = time.time() + 30
final_status = ""
while time.time() < deadline:
    r = httpx.get(f"{API_BASE}/orders/{order_id}")
    final_status = r.json()["status"]
    if final_status in ("shipped", "exception"):
        break
    time.sleep(1)
report("4.1  Pipeline finished", final_status in ("shipped", "exception"), f"status={final_status}")

ext_id = f"KSQL-TEST-{TS}"

print("\n  Querying ORDER_VALIDATED stream...")
rows = ksql_query(
    f"SELECT ORDER_ID, EXTERNAL_ORDER_ID FROM ORDER_VALIDATED "
    f"WHERE EXTERNAL_ORDER_ID = '{ext_id}' EMIT CHANGES LIMIT 1;"
)
report("4.2  Order in ORDER_VALIDATED", len(rows) >= 1, f"{len(rows)} row(s)")

print("  Querying ORDER_ERP_CREATED stream...")
rows = ksql_query(
    "SELECT ORDER_ID, ERP_ORDER_ID FROM ORDER_ERP_CREATED EMIT CHANGES LIMIT 10;"
)
report("4.3  Order in ORDER_ERP_CREATED", len(rows) >= 1, f"{len(rows)} row(s)")

print("  Querying ORDER_ALLOCATED stream...")
rows = ksql_query(
    "SELECT ORDER_ID, RESERVATIONS FROM ORDER_ALLOCATED EMIT CHANGES LIMIT 10;"
)
report("4.4  Order in ORDER_ALLOCATED", len(rows) >= 1, f"{len(rows)} row(s)")

if final_status == "shipped":
    print("  Querying SHIPMENT_CREATED stream...")
    rows = ksql_query(
        "SELECT ORDER_ID, SHIPMENT_ID, CARRIER, TRACKING_NUMBER "
        "FROM SHIPMENT_CREATED EMIT CHANGES LIMIT 10;"
    )
    report("4.5  Shipment in SHIPMENT_CREATED", len(rows) >= 1, f"{len(rows)} row(s)")
    if rows:
        print(f"       carrier:  {rows[-1].get('CARRIER')}")
        print(f"       tracking: {rows[-1].get('TRACKING_NUMBER')}")


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 5 — Materialized table: orders by channel
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 5: Materialized table — ORDERS_BY_CHANNEL")

print("\n  Pull query on ORDERS_BY_CHANNEL...")
rows = ksql_query("SELECT CHANNEL, ORDER_COUNT FROM ORDERS_BY_CHANNEL;", earliest=False)
report("5.1  Table returns rows", len(rows) >= 1, f"{len(rows)} channel(s)")
for row in rows:
    print(f"       {row.get('CHANNEL')}: {row.get('ORDER_COUNT')} orders")

ksql_ch = [r for r in rows if r.get("CHANNEL") == "ksql-test"]
report("5.2  'ksql-test' channel counted", len(ksql_ch) >= 1,
       f"count={ksql_ch[0].get('ORDER_COUNT') if ksql_ch else 0}")


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 6 — Materialized table: shipments by carrier
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 6: Materialized table — SHIPMENTS_BY_CARRIER")

print("\n  Pull query on SHIPMENTS_BY_CARRIER...")
rows = ksql_query("SELECT CARRIER, SHIPMENT_COUNT FROM SHIPMENTS_BY_CARRIER;", earliest=False)
report("6.1  Table returns rows", len(rows) >= 1, f"{len(rows)} carrier(s)")
for row in rows:
    print(f"       {row.get('CARRIER')}: {row.get('SHIPMENT_COUNT')} shipments")


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 7 — Persistent queries running
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 7: Persistent queries running")

print("\n  SHOW QUERIES...")
resp = ksql_execute("SHOW QUERIES;")
queries = resp[0].get("queries", [])
print(f"       {len(queries)} persistent queries")
for q in queries:
    print(f"       {q.get('id', '?')}: {q.get('queryString', '?')[:60]}...")
report("7.1  At least 3 persistent queries", len(queries) >= 3, f"{len(queries)} queries")


# ─────────────────────────────────────────────────────────────────────────────
#  Scenario 8 — Multiple orders, verify aggregation updates
# ─────────────────────────────────────────────────────────────────────────────
section("Scenario 8: Batch orders — aggregation updates")

batch_channel = f"ksql-batch-{TS}"
print(f"\n  Submitting 3 orders on '{batch_channel}' channel...")
for i in range(3):
    payload = {
        "external_order_id": f"KSQL-BATCH-{TS}-{i}",
        "channel": batch_channel,
        "customer_name": f"Batch KSQL User {i}",
        "shipping_address": f"{i}00 Batch Blvd",
        "items": [{"sku": f"KB-{i}", "product_name": f"Batch Item {i}", "quantity": 1, "unit_price": 15.00}],
    }
    r = httpx.post(f"{API_BASE}/orders/import", json=payload)
    print(f"       Order {i}: {r.json()['id']}  ({r.status_code})")

print("\n  Waiting for events to propagate...")
time.sleep(5)

print(f"  Pull query on ORDERS_BY_CHANNEL for '{batch_channel}'...")
rows = ksql_query("SELECT CHANNEL, ORDER_COUNT FROM ORDERS_BY_CHANNEL;", earliest=False)
batch_row = [r for r in rows if r.get("CHANNEL") == batch_channel]
count = batch_row[0].get("ORDER_COUNT", 0) if batch_row else 0
report("8.1  Batch channel has 3 orders", count == 3, f"count={count}")


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
