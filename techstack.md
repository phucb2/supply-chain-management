# Technology Stack

Recommended technologies for the Supply Chain Order Integration Platform described in `system-design.md`.
Reference against `business.md` for business requirement traceability.

---

## 1. Overview

| Layer                | Technology                            | Purpose                                      |
| -------------------- | ------------------------------------- | -------------------------------------------- |
| API Service          | Python / FastAPI                      | REST endpoints, webhook receiver, Kafka producer |
| Stream Processor     | Python / Faust                        | Kafka consumer, async pipeline, real-time logic |
| Event Bus            | Apache Kafka                          | Async messaging, event streaming, deduplication |
| Operational Database | PostgreSQL                            | Transactional data, order state, audit trail |
| Object Storage       | MinIO                                 | Raw payload archive, labels, logs, backups   |
| ML Training          | MLflow                                | ETA model training on historical data        |
| ML Serving           | Faust (inline)                        | Real-time ETA prediction                     |
| Observability        | OpenTelemetry + Prometheus + Grafana + Loki + Tempo | Metrics, tracing, logs, dashboards |
| Deployment           | Docker Compose                        | Full-stack local and deployment environment  |

---

## 2. Layer-by-layer rationale

### A. Backend Services — Python / FastAPI

Two application services instead of many microservices — simpler to build, deploy, and debug.

Why FastAPI:

* async-native (`asyncio`) — fits the async-first architecture
* automatic OpenAPI docs for every internal API
* Pydantic models map directly to the canonical order model
* Python ecosystem aligns with ML requirements (R9, R10)

Service structure:

```text
services/
├── api/                  # FastAPI — all REST endpoints and Kafka producers
│   ├── routes/
│   │   ├── orders.py
│   │   ├── shipments.py
│   │   ├── warehouse.py
│   │   └── webhooks.py
│   ├── models.py         # Pydantic canonical models
│   ├── db.py             # SQLAlchemy models + queries
│   └── kafka_producer.py
│
└── stream_processor/     # Faust — Kafka consumer, real-time logic
    ├── agents/
    │   ├── order_pipeline.py    # validate → ERP sync → allocate
    │   ├── shipment_tracker.py  # tracking updates, status sync
    │   └── eta_predictor.py     # ML inference on events
    └── app.py
```

**api** — single FastAPI app that exposes all REST/webhook endpoints, writes to PostgreSQL, and publishes events to Kafka. Covers order ingestion, warehouse ops (R6), driver management (R7), and webhook alerts (R5).

**stream_processor** — single Faust app that consumes Kafka topics and runs the async pipeline: order validation, ERP sync (mocked), inventory allocation, shipment creation, notification, and real-time ETA inference (R10).

Key libraries:

| Library                  | Purpose                                  |
| ------------------------ | ---------------------------------------- |
| `fastapi`                | HTTP framework                           |
| `pydantic`               | Canonical model, validation              |
| `sqlalchemy` + `alembic` | ORM and DB migrations                    |
| `confluent-kafka`        | Kafka producer (api service)             |
| `faust-streaming`        | Kafka Streams in Python (stream processor) |
| `opentelemetry-*`        | Auto-instrumentation for tracing/metrics |
| `structlog`              | Structured JSON logging                  |

---

### B. Event Bus — Apache Kafka

Handles: decoupling all services, event sourcing, traffic spike absorption.

Why Kafka:

* high-throughput ingestion for peak promotions (R4, scalability §10)
* event replay for audit and reconciliation (R8, §L)
* partitioning by `order_id` keeps ordering guarantees per order
* durable log — acts as the system of record for events
* no vendor lock-in (self-hosted or Confluent OSS)

Topic design (maps to system-design §D):

```text
order.received
order.validated
order.erp.create
order.erp.created
order.allocated
shipment.requested
shipment.created
shipment.status-updated
order.cancelled
order.exception
dlq.*                    # dead-letter queues per topic
```

---

### C. Stream Processing — Faust (Kafka Streams for Python)

Handles: order pipeline processing, real-time tracking (R1, R2), ETA inference (R10), alert triggers (R5).

Why Faust:

* Python-native — no JVM needed, same language as the API service
* Kafka Streams semantics (agents, tables, windowing)
* runs as a single process — the `stream_processor` service
* already coupled to Kafka — no extra infrastructure

---

### D. Operational Database — PostgreSQL

Handles: orders, order_items, order_events, shipments, shipment_packages, integration_requests, inventory_reservations (all tables from §6).

Why PostgreSQL:

* ACID transactions — critical for idempotency and outbox pattern (§8D)
* `ON CONFLICT` for upsert-based deduplication
* JSONB columns for raw payloads and flexible event data
* read replicas for dashboards and reporting queries (§10)
* partitioning (by `created_at`) for order_events table growth
* mature, open-source, no vendor lock-in

Schema conventions:

* UUID primary keys
* `created_at` / `updated_at` timestamps with timezone
* soft deletes via `deleted_at`
* outbox table: `outbox_events (id, aggregate_type, aggregate_id, event_type, payload, published_at)`

---

### E. Object Storage — MinIO

Handles: raw webhook payload archive, shipping labels, batch report output, log backup.

Why MinIO:

* S3-compatible API — portable to AWS S3 if needed
* self-hosted, no vendor lock-in (business.md NFR)
* stores large blobs that don't belong in PostgreSQL

Bucket structure:

```text
raw-payloads/          # incoming webhook bodies
shipping-labels/       # PDF/ZPL label files
reports/               # monthly/quarterly batch reports (R8)
ml-artifacts/          # trained model files
backups/               # DB dumps, Kafka topic snapshots
```

---

### F. ML — MLflow + Faust

**Batch training (R9):**

* MLflow for experiment tracking, model registry, artifact storage (MinIO backend)
* Train ETA model on historical shipment data from PostgreSQL
* Use pandas for feature engineering

**Streaming inference (R10):**

* Trained model loaded into the `eta_predictor` Faust agent
* Consumes `shipment.status-updated` events
* Produces real-time ETA predictions back to a response topic or serves via REST

---

### G. Observability — OpenTelemetry + Prometheus + Grafana + Loki + Tempo

Maps to system-design §11. OpenTelemetry is the **single instrumentation layer** across all services — it collects traces, metrics, and logs and exports them to the backends below.

#### OpenTelemetry integration

Every FastAPI service is instrumented via the `opentelemetry-instrumentation-fastapi` auto-instrumentation package. OTel also instruments Kafka producers/consumers, `httpx` calls, and SQLAlchemy queries automatically.

What OTel provides:

* **Trace context propagation** — a single `trace_id` follows an order from webhook receipt through Kafka, ERP call, shipment creation, and carrier response. Viewing one trace shows the full order lifecycle.
* **Span-level detail** — each service operation (validate order, call ERP API, generate label) is a span with timing, status, and attributes like `order_id`, `channel`, `carrier`.
* **Metrics export** — request count, latency histograms, error rates per service, exported to Prometheus.
* **Log correlation** — `trace_id` and `span_id` injected into every structured log line, so logs can be cross-referenced with traces in Grafana.

OTel SDK packages used:

| Package                                        | Purpose                             |
| ---------------------------------------------- | ----------------------------------- |
| `opentelemetry-sdk`                            | Core SDK                            |
| `opentelemetry-exporter-otlp`                  | Export traces/metrics to collector   |
| `opentelemetry-instrumentation-fastapi`        | Auto-instrument HTTP endpoints      |
| `opentelemetry-instrumentation-httpx`          | Trace outgoing HTTP calls (ERP, carrier) |
| `opentelemetry-instrumentation-sqlalchemy`     | Trace DB queries                    |
| `opentelemetry-instrumentation-confluent-kafka`| Trace Kafka produce/consume         |

Architecture:

```text
api (FastAPI)          ──┐
stream_processor (Faust) ┘── OTel SDK ──► OTel Collector ──┬──► Tempo      (traces)
                                                            ├──► Prometheus (metrics)
                                                            └──► Loki       (logs)
                                                                     │
                                                                Grafana (dashboards)
```

#### Backend tools

| Tool          | Role                       | What it tracks                                   |
| ------------- | -------------------------- | ------------------------------------------------ |
| OTel Collector| Central telemetry pipeline | Receives all signals, fans out to backends       |
| Prometheus    | Metrics storage            | Orders/min, ERP latency, DLQ depth, error rates  |
| Grafana       | Dashboards & alerting      | Per-service, per-integration, SLA dashboards     |
| Loki          | Log aggregation            | Structured JSON logs with trace_id correlation   |
| Tempo         | Distributed trace storage  | End-to-end order flow via OpenTelemetry spans    |

#### Example: tracing an order end-to-end

A single trace for order `ORD-12345` would contain spans like:

```text
[trace_id: abc123]
├── POST /orders/import (api service)                 12ms
│   ├── store_raw_payload (postgresql INSERT ON CONFLICT) 4ms
│   └── publish order.received (kafka produce)            2ms
├── order_pipeline agent (stream processor)           285ms
│   ├── validate_order                                 15ms
│   │   ├── check_sku (postgresql SELECT)               2ms
│   │   └── publish order.validated (kafka produce)     1ms
│   ├── sync_erp (mocked)                            250ms
│   │   └── publish order.erp.created (kafka produce)   1ms
│   ├── allocate_inventory                             20ms
│   └── create_shipment                              180ms
│       ├── POST /api/shipments (httpx → carrier)    160ms
│       └── publish shipment.created (kafka produce)    1ms
└── notify_channel (stream processor)                  30ms
    └── PUT /orders/{id}/fulfillments (httpx → Shopify) 25ms
```

Alerting rules (Grafana):

* orders stuck > 15 min in any state
* ERP error rate > 5%
* DLQ message count > 0
* shipment creation p99 latency > 10s

---

### H. Deployment — Docker Compose

All services and infrastructure run via a single `docker-compose.yml`. This keeps the setup reproducible and easy to run on any machine for development, demos, and grading.

```yaml
# docker-compose.yml structure
services:
  # --- Infrastructure ---
  kafka:
    image: confluentinc/cp-kafka (KRaft mode)
  postgresql:
    image: postgres:16
  minio:
    image: minio/minio

  # --- Observability ---
  otel-collector:
    image: otel/opentelemetry-collector-contrib
  prometheus:
    image: prom/prometheus
  grafana:
    image: grafana/grafana
  loki:
    image: grafana/loki
  tempo:
    image: grafana/tempo

  # --- Application (just 2 services) ---
  api:
    build: ./services/api
  stream-processor:
    build: ./services/stream_processor
```

Why Docker Compose only:

* single command startup (`docker compose up`)
* no Kubernetes complexity for a university assignment
* all dependencies version-pinned and reproducible
* easy to add/remove services

---

## 3. Requirement traceability

| Requirement | Description                         | Technologies                              |
| ----------- | ----------------------------------- | ----------------------------------------- |
| R1          | Real-time tracking updates          | Kafka, Faust (stream processor), OTel     |
| R2          | Customer shipment monitoring        | Faust, FastAPI (api service)              |
| R3          | Duplicate order rejection           | PostgreSQL (unique constraint), Kafka     |
| R4          | Order sync from e-commerce/ERP      | FastAPI (api), Kafka, Faust (stream proc) |
| R5          | Webhook alerts on shipment events   | Kafka, FastAPI (api)                      |
| R6          | Goods-in / goods-out recording      | FastAPI (api), PostgreSQL                 |
| R7          | Driver / vendor management          | FastAPI (api), PostgreSQL                 |
| R8          | Monthly/quarterly reports           | PostgreSQL, MinIO                         |
| R9          | ETA model training (batch)          | MLflow, PostgreSQL, MinIO                 |
| R10         | Real-time ETA predictions           | Faust (stream processor), MLflow          |

---

## 4. Development environment

Start everything:

```bash
docker compose up -d
```

Exposed ports (defaults):

| Service        | Port  |
| -------------- | ----- |
| API Service    | 8000  |
| Grafana        | 3000  |
| Prometheus     | 9090  |
| MinIO Console  | 9001  |
| PostgreSQL     | 5432  |
| Kafka          | 9092  |
| OTel Collector | 4318  |

Recommended developer tools:

| Tool        | Purpose                         |
| ----------- | ------------------------------- |
| `ruff`      | Python linter + formatter       |
| `pytest`    | Unit and integration testing    |
| `httpie`    | Manual API testing              |
| `kcat`      | Kafka topic inspection          |
| `pgcli`     | PostgreSQL interactive client   |
