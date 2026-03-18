\Here’s a solid system design for **taking orders from e-commerce, syncing to ERP, and creating shipments**.

## 1. Goal

Build a platform that:

* receives orders from e-commerce channels
* validates and transforms them
* pushes them into ERP
* allocates inventory
* triggers fulfillment and shipment creation
* returns shipment/tracking updates back to upstream systems

Flow:

**e-Commerce / Marketplace → Order Integration Platform → ERP → WMS / Shipment / Carrier**

---

## 2. Core requirements

### Functional

* Ingest orders from multiple channels
* Deduplicate and validate incoming orders
* Map external order format to internal canonical model
* Create or update sales orders in ERP
* Reserve or allocate inventory
* Trigger shipment creation
* get label + tracking number from carrier/3PL
* send shipment status back to e-commerce platform
* support cancellations, partial shipments, returns
* provide audit trail and reconciliation

### Non-functional

* high reliability
* no duplicate order creation
* eventual consistency across systems
* retry-safe integrations
* observability and replay
* scalability for peak events
* security and access control

---

## 3. High-level architecture

```text
+------------------+       +---------------------+       +------------------+
| e-Commerce APIs  | ----> | API Gateway /       | ----> | Order Ingestion  |
| Shopify/Amazon   |       | Webhook Receiver    |       | Service          |
+------------------+       +---------------------+       +------------------+
                                                              |
                                                              v
                                                     +------------------+
                                                     | Validation /     |
                                                     | Transformation   |
                                                     +------------------+
                                                              |
                                                              v
                                                     +------------------+
                                                     | Message Bus /    |
                                                     | Event Queue      |
                                                     +------------------+
                                                              |
                    +------------------+----------------------+-------------------+
                    |                  |                                          |
                    v                  v                                          v
          +------------------+  +------------------+                    +------------------+
          | ERP Connector    |  | Inventory / ATP  |                    | Order State      |
          | Adapter          |  | Service          |                    | Service          |
          +------------------+  +------------------+                    +------------------+
                    |                                                         |
                    v                                                         v
             +-------------+                                          +------------------+
             | ERP System   |                                          | Audit / Tracking |
             +-------------+                                          +------------------+
                    |
                    v
          +------------------+
          | Fulfillment /    |
          | WMS Orchestrator |
          +------------------+
                    |
                    v
          +------------------+
          | Shipment Service |
          +------------------+
                    |
                    v
          +------------------+
          | Carrier / 3PL    |
          | APIs             |
          +------------------+
                    |
                    v
          +------------------+
          | Notifications /  |
          | Status Sync      |
          +------------------+
                    |
                    v
          +------------------+
          | e-Commerce       |
          | Update API       |
          +------------------+
```

---

## 4. Main components

## A. API Gateway / Webhook Receiver

Receives orders from storefronts and marketplaces.

Responsibilities:

* authenticate source
* rate limiting
* signature verification for webhooks
* schema validation
* push request into ingestion pipeline quickly

Why:

* do not do heavy processing inline
* acknowledge webhook fast, process asynchronously

---

## B. Order Ingestion Service

Creates a canonical order record.

Responsibilities:

* parse incoming order
* assign correlation ID
* store raw payload
* deduplicate using idempotency key
* emit `OrderReceived` event

Idempotency key examples:

* `channel + external_order_id`
* or event ID from webhook source

---

## C. Validation / Transformation Service

Normalizes channel-specific formats into one internal model.

Canonical order model:

```text
Order
- order_id
- external_order_id
- channel
- customer
- billing_address
- shipping_address
- line_items[]
- currency
- taxes
- discounts
- payment_status
- fulfillment_status
- requested_shipping_method
- created_at
```

Responsibilities:

* validate SKU exists
* validate address
* validate totals
* translate channel fields into ERP-friendly model
* enrich with business rules

Example:

* Shopify, WooCommerce, Amazon all map into same internal schema

---

## D. Message Bus / Queue

Decouples stages and improves resilience.

Use:

* Kafka / Pulsar for event streaming
* SQS / RabbitMQ for simpler queue-based workflow

Topics / queues:

* `order.received`
* `order.validated`
* `order.erp.create`
* `order.erp.updated`
* `shipment.requested`
* `shipment.created`
* `shipment.failed`
* `order.cancelled`

Why:

* absorbs traffic spikes
* allows retries
* decouples services

---

## E. Order State Service

Tracks lifecycle of each order.

State examples:

* RECEIVED
* VALIDATED
* ERP_PENDING
* ERP_CREATED
* ALLOCATED
* READY_TO_SHIP
* SHIPMENT_CREATED
* SHIPPED
* DELIVERED
* FAILED
* CANCELLED

Responsibilities:

* maintain current state
* support query by order ID
* show step-by-step history
* drive UI and ops dashboard

This is critical because ERP, WMS, and carrier are all asynchronous.

---

## F. ERP Connector

Integration layer between your platform and ERP.

Responsibilities:

* convert canonical order to ERP API/file format
* create sales order in ERP
* update existing ERP order
* query ERP order/invoice/allocation status
* handle ERP errors and retries

Design:

* use adapter pattern per ERP
* example adapters:

  * SAP adapter
  * Oracle adapter
  * NetSuite adapter
  * Dynamics adapter

Why adapter layer matters:

* every ERP is different
* keeps core platform independent

---

## G. Inventory / ATP Service

ATP = Available To Promise.

Responsibilities:

* check stock availability
* reserve stock
* select fulfillment location
* support split shipment logic

Rules:

* choose nearest warehouse
* choose warehouse with full availability
* split if needed
* prioritize low shipping cost or SLA

This service may either:

* read inventory from ERP
* or maintain a near-real-time replicated inventory view

---

## H. Fulfillment / WMS Orchestrator

Bridges order management and shipping execution.

Responsibilities:

* create pick/pack requests
* split order into shipment groups
* route to warehouse / 3PL
* wait for pack confirmation
* then request shipping label

If company has WMS:

* integrate with WMS directly

If not:

* shipment service may handle simpler fulfillment logic itself

---

## I. Shipment Service

Creates actual shipment requests.

Responsibilities:

* determine carrier/service level
* generate shipment labels
* get tracking number
* store package metadata
* support single- and multi-package shipments

Inputs:

* ship-from warehouse
* ship-to address
* package weight/dimensions
* service level
* customs data if international

Outputs:

* shipment ID
* label URL/file
* tracking number
* estimated delivery

---

## J. Carrier / 3PL Integration

Connects to FedEx, UPS, DHL, local carriers, or aggregator APIs.

Responsibilities:

* rate quote
* label generation
* tracking updates
* pickup requests
* exception events

Usually best to hide carrier complexity behind a carrier abstraction layer:

```text
CarrierAdapter
- createShipment()
- cancelShipment()
- getRates()
- trackShipment()
```

---

## K. Notification / Sync-back Service

Pushes downstream results upstream.

Responsibilities:

* notify e-commerce channel of fulfillment
* update tracking info
* send customer notifications
* sync statuses to ERP and storefront

Example:

* mark Shopify order fulfilled
* add tracking number
* send email/SMS

---

## L. Reconciliation / Audit Service

Important in real systems.

Responsibilities:

* compare e-commerce orders vs ERP orders
* compare ERP shipment status vs carrier status
* detect missing/duplicate records
* generate exception reports
* allow replay

Without this, operations will struggle when systems drift.

---

## 5. Main data flow

## Happy path

### Step 1: Order arrives

* e-commerce platform sends webhook or API call
* gateway validates request
* order stored as raw payload
* dedupe check
* event published: `OrderReceived`

### Step 2: Normalize and validate

* transform into canonical model
* validate SKU, address, totals
* store order state = `VALIDATED`

### Step 3: Create ERP order

* publish `CreateERPOrder`
* ERP connector calls ERP API
* ERP returns internal sales order ID
* state = `ERP_CREATED`

### Step 4: Inventory allocation

* inventory service checks stock
* reserve inventory
* if partial stock, split or backorder
* state = `ALLOCATED`

### Step 5: Fulfillment request

* orchestrator creates pick/pack task in WMS or 3PL
* warehouse confirms packed packages

### Step 6: Shipment creation

* shipment service calls carrier
* receives label + tracking number
* state = `SHIPMENT_CREATED`

### Step 7: Upstream sync

* update ERP fulfillment info
* update e-commerce order tracking
* notify customer
* state = `SHIPPED`

### Step 8: Delivery/tracking events

* carrier webhook updates shipment progress
* final state eventually becomes `DELIVERED`

---

## 6. Database design

Use a relational DB for transactional integrity plus event storage.

### Main tables

### orders

* id
* external_order_id
* channel
* customer_id
* currency
* total_amount
* payment_status
* current_state
* erp_order_id
* created_at
* updated_at

### order_items

* id
* order_id
* sku
* quantity
* unit_price
* tax
* discount

### order_events

* id
* order_id
* event_type
* payload
* created_at

### shipments

* id
* order_id
* carrier
* carrier_service
* tracking_number
* label_url
* shipment_status
* warehouse_id

### shipment_packages

* id
* shipment_id
* weight
* dimensions
* package_type

### integration_requests

* id
* system_name
* request_type
* idempotency_key
* request_payload
* response_payload
* status
* retry_count

### inventory_reservations

* id
* order_id
* sku
* warehouse_id
* reserved_qty
* status

---

## 7. API design

### Internal APIs

#### Order ingestion

```http
POST /orders/import
```

#### Get order status

```http
GET /orders/{id}
```

#### Retry failed integration

```http
POST /orders/{id}/retry
```

#### Cancel order

```http
POST /orders/{id}/cancel
```

#### Create shipment

```http
POST /shipments
```

#### Carrier webhook

```http
POST /carrier-events
```

---

## 8. Key design decisions

## A. Canonical data model

Do not let every service understand every channel schema.

Use:

* one canonical order model
* adapter per channel
* adapter per ERP
* adapter per carrier

This prevents combinatorial explosion.

---

## B. Async-first architecture

Avoid synchronous end-to-end processing.

Why:

* ERP may be slow
* carrier APIs may timeout
* WMS may process later
* webhooks should return quickly

Pattern:

* accept
* persist
* enqueue
* process asynchronously

---

## C. Idempotency everywhere

This is one of the most important design rules.

Where:

* webhook processing
* ERP order creation
* shipment creation
* status updates

Example:
If Shopify retries a webhook, system must not create a second ERP order.

---

## D. Outbox pattern

Use outbox pattern when publishing events after DB transaction.

Why:

* avoid “DB commit succeeded but event publish failed”
* ensure reliable event delivery

Typical design:

* write business row + outbox event in same transaction
* background worker publishes outbox rows

---

## E. Saga / orchestration for multi-step workflow

There is no distributed transaction across e-commerce, ERP, WMS, and carrier.

Use saga pattern:

* each step commits locally
* failures trigger compensation

Examples:

* ERP order created but shipment creation fails → retry or mark exception
* shipment created but order cancelled → attempt shipment cancel

---

## 9. Failure handling

## Common failure cases

### Duplicate order events

Solution:

* unique constraint on `(channel, external_order_id)`
* idempotency token store

### ERP down

Solution:

* retry with backoff
* dead-letter queue
* ops dashboard for replay

### Invalid SKU

Solution:

* put order in exception state
* manual resolution queue

### Inventory unavailable

Solution:

* partial allocation
* backorder
* warehouse reroute

### Carrier label generation failed

Solution:

* retry
* fallback carrier
* hold shipment

### Shipment created twice

Solution:

* carrier request idempotency
* store shipment external reference

---

## 10. Scalability

### Read/write pattern

* spikes during promotions
* order ingestion heavy writes
* status queries heavy reads

### Scale strategy

* stateless services horizontally scaled
* queue partitions by order ID
* DB read replicas for dashboards
* cache for product/address validation
* batch sync for non-critical updates

### Hot paths

* webhook receiver
* ERP connector
* shipment service

---

## 11. Observability

You’ll need strong monitoring.

Track:

* orders received per minute
* validation failures
* ERP success/failure rate
* shipment creation latency
* stuck orders by state
* DLQ count
* reconciliation mismatches

Also include:

* correlation IDs
* distributed tracing
* structured logs
* per-integration dashboards

---

## 12. Security

* API authentication
* webhook signature verification
* encryption in transit and at rest
* RBAC for ops/admin tools
* audit logs
* secrets manager for ERP/carrier credentials

---