# Implementation Plan — Order Pipeline & Shipment Tracker

Step-by-step guide to implement the order and shipment flows. Use after project skeleton is running.

---

## Current state

All stubs raise `NotImplementedError`. DB schema exists in PostgreSQL. Kafka topics created. Faust and FastAPI containers running.

What works: health check, Docker Compose stack, empty route/agent skeletons.

What doesn't: every business endpoint and stream agent.

---

## Phase 1 — Order Ingestion (API service)

Goal: `POST /orders/import` accepts an order, deduplicates, persists, publishes to Kafka.

### Step 1.1 — Repository layer

Create `services/api/app/db/repository.py` with async functions:

- `create_order(session, order_data) → Order` — INSERT with `ON CONFLICT (external_order_id) DO NOTHING`, return existing if duplicate
- `get_order(session, order_id) → Order | None` — SELECT by UUID, eager-load items
- `list_orders(session, skip, limit, status_filter) → list[Order]` — paginated query
- `create_order_event(session, order_id, event_type, payload)` — append to audit trail
- `update_order_status(session, order_id, new_status) → Order` — UPDATE status + insert event

### Step 1.2 — Implement `POST /orders/import`

In `routes/orders.py`:

1. Parse request body with `OrderCreate` schema
2. Call `create_order()` — if duplicate, return `409 Conflict`
3. Store raw JSON payload in `raw_payload` column
4. Insert `order_items` rows
5. Insert `order_event` with type `order.received`
6. Publish `order.received` to Kafka via `publish_event(topic, key=order_id, value)`
7. Return `201` with `OrderResponse`

Idempotency: `external_order_id` unique constraint handles retried webhooks.

### Step 1.3 — Implement read endpoints

- `GET /orders/{order_id}` — fetch by UUID, return `OrderResponse` or `404`
- `GET /orders/` — paginated list with optional `?status=` and `?channel=` filters

### Step 1.4 — Implement `POST /orders/{order_id}/cancel`

1. Fetch order, verify cancellable state (not `shipped`/`delivered`)
2. Update status to `cancelled`
3. Publish `order.cancelled` to Kafka
4. Return updated `OrderResponse`

### Step 1.5 — Raw payload archive to MinIO

Create `services/api/app/storage.py`:

- `upload_raw_payload(order_id, payload_bytes)` — write to `raw-payloads/{date}/{order_id}.json`
- Use `minio` Python SDK (`pip install minio`)
- Call from `import_order` after DB insert (fire-and-forget, log on failure)

---

## Phase 2 — Order Pipeline (Stream Processor)

Goal: Faust agent consumes `order.received`, runs validate → ERP sync → allocate → create shipment.

### Step 2.1 — DB access from stream processor

Create `services/stream_processor/app/db.py`:

- Async SQLAlchemy session factory (reuse same pattern as API service)
- Functions: `get_order()`, `update_order_status()`, `create_order_event()`, `create_shipment()`, `create_inventory_reservation()`

### Step 2.2 — Validate order

In `order_pipeline.py`, after consuming `OrderReceived`:

1. Load order from DB by `order_id`
2. Validate:
   - All SKUs exist (for now, accept all — placeholder check)
   - Required fields present
   - Order not already past `validated` state (idempotent re-processing)
3. On success: update status → `validated`, publish `order.validated`
4. On failure: update status → `exception`, publish `order.exception` with reason

### Step 2.3 — ERP sync (mocked)

Create `services/stream_processor/app/adapters/erp.py`:

- `async def create_erp_order(order) → ERPResponse` — mock adapter
- Simulate: random latency (200–500ms via `asyncio.sleep`), 95% success rate
- Returns mock `erp_order_id`

In pipeline, after validation:

1. Call `create_erp_order()`
2. On success: update status → `erp_synced`, store `erp_order_id` in event payload, publish `order.erp.created`
3. On failure: publish to `order.exception`, update status → `exception`

### Step 2.4 — Inventory allocation

Create `services/stream_processor/app/adapters/inventory.py`:

- `async def allocate_inventory(order_id, items) → list[Reservation]`
- For each item: INSERT into `inventory_reservations` with status `reserved`
- For now, always succeed (no real stock check)

In pipeline, after ERP sync:

1. Call `allocate_inventory()`
2. Update status → `allocated`, publish `order.allocated`

### Step 2.5 — Shipment creation

Create `services/stream_processor/app/adapters/carrier.py`:

- `async def create_shipment(order, reservations) → ShipmentResult` — mock carrier
- Returns mock `tracking_number`, `carrier` name, `label_url`

In pipeline, after allocation:

1. Call `create_shipment()`
2. INSERT into `shipments` table with status `created`
3. INSERT into `shipment_packages` if applicable
4. Update order status → `shipped`
5. Publish `shipment.created`

### Step 2.6 — Error handling & DLQ

Wrap the entire pipeline in try/except:

- On transient error: log + let Faust retry (default behavior)
- On permanent error (validation, bad data): publish to `dlq.order.received` with original event + error reason
- Update order status to `exception`

---

## Phase 3 — Shipment Tracking (API + Stream Processor)

Goal: drivers push status updates → Kafka → stream processor updates DB → triggers webhooks.

### Step 3.1 — `POST /shipments/{shipment_id}/status`

In `routes/shipments.py`:

1. Parse `TrackingEvent` from request body
2. Verify shipment exists, return `404` if not
3. Publish `shipment.status-updated` to Kafka with key = `shipment_id`
4. Return `202 Accepted`

### Step 3.2 — `GET /shipments/{shipment_id}`

1. Query `shipments` table by UUID, eager-load packages
2. Return `ShipmentResponse` or `404`

### Step 3.3 — `GET /shipments/{shipment_id}/tracking`

1. Query `order_events` where `event_type LIKE 'shipment.%'` and related to shipment's order
2. Return chronological list of tracking events

### Step 3.4 — Shipment tracker agent

In `shipment_tracker.py`, after consuming `ShipmentStatusUpdated`:

1. Load shipment from DB
2. Update `shipments.status` to new status
3. Insert `order_event` with type `shipment.status-updated` and location/timestamp payload
4. If status is `delivered`:
   - Update order status → `delivered`
   - Insert final `order_event`
5. If status is `exception`:
   - Update order status → `exception`

### Step 3.5 — Webhook dispatch

Create `services/stream_processor/app/webhooks.py`:

- `async def dispatch_webhooks(event_type, payload)`
- Query `webhook_subscriptions` table for matching `event_type`
- For each active subscription:
  - POST payload to `subscription.url`
  - If `secret` set, include HMAC signature header
  - Fire-and-forget with timeout, log failures
- Called from `shipment_tracker` agent after DB update

---

## Phase 4 — Webhook Management (API service)

Goal: CRUD for webhook subscriptions (R5).

### Step 4.1 — `POST /webhooks/subscriptions`

1. Parse `WebhookSubscription` schema
2. INSERT into `webhook_subscriptions` table
3. Return `201` with subscription ID

### Step 4.2 — `GET /webhooks/subscriptions`

1. List all active subscriptions

### Step 4.3 — `POST /webhooks/inbound`

1. Receive carrier/channel webhook
2. Store raw payload in MinIO
3. Determine event type from payload
4. Publish to appropriate Kafka topic (e.g., `shipment.status-updated`)
5. Return `200 OK` fast

---

## Phase 5 — Integration testing

### Step 5.1 — End-to-end happy path

Write a test script or pytest that:

1. POST an order to `/orders/import`
2. Wait for pipeline to process (poll `GET /orders/{id}` until status = `shipped`)
3. POST a tracking update to `/shipments/{id}/status` with `in_transit`
4. POST another with `delivered`
5. Verify `GET /orders/{id}` shows status = `delivered`
6. Verify `GET /shipments/{id}/tracking` shows all events

### Step 5.2 — Duplicate rejection

1. POST same order twice (same `external_order_id`)
2. Second call returns `409`
3. Only one order exists in DB

### Step 5.3 — Cancellation

1. POST order, wait until `validated`
2. POST cancel
3. Verify status = `cancelled`
4. Verify `order.cancelled` event in DB

### Step 5.4 — Error path

1. Trigger ERP failure (if mock has failure rate)
2. Verify order lands in `exception` state
3. Verify DLQ message exists

---

## Suggested implementation order

| Priority | Task                         | Files to change                                                    |
| -------- | ---------------------------- | ------------------------------------------------------------------ |
| 1        | Repository layer             | `api/app/db/repository.py` (new)                                   |
| 2        | Order import endpoint        | `api/app/routes/orders.py`                                         |
| 3        | Order read endpoints         | `api/app/routes/orders.py`                                         |
| 4        | Order pipeline agent         | `stream_processor/app/agents/order_pipeline.py`                    |
| 5        | Mock ERP adapter             | `stream_processor/app/adapters/erp.py` (new)                       |
| 6        | Mock inventory allocation    | `stream_processor/app/adapters/inventory.py` (new)                 |
| 7        | Mock carrier / shipment      | `stream_processor/app/adapters/carrier.py` (new)                   |
| 8        | DB access in stream proc     | `stream_processor/app/db.py` (new)                                 |
| 9        | Shipment status endpoint     | `api/app/routes/shipments.py`                                      |
| 10       | Shipment tracker agent       | `stream_processor/app/agents/shipment_tracker.py`                  |
| 11       | Webhook dispatch             | `stream_processor/app/webhooks.py` (new)                           |
| 12       | Webhook CRUD endpoints       | `api/app/routes/webhooks.py`                                       |
| 13       | MinIO raw payload archiver   | `api/app/storage.py` (new)                                         |
| 14       | Order cancel endpoint        | `api/app/routes/orders.py`                                         |
| 15       | Integration tests            | `tests/integration/` (new)                                         |
