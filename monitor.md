# Monitoring & Logging Plan

Observability implementation plan using OpenTelemetry, Grafana, Loki, Tempo, and Prometheus.  
Reference this when building out the monitoring stack.

---

## Current State

| Component | Status |
|-----------|--------|
| OTel Collector | Deployed — pipelines for traces→Tempo, metrics→Prometheus, logs→Loki |
| API telemetry | Traces only (OTLP gRPC + FastAPI auto-instrumentation) |
| Stream processor telemetry | OTel deps in `requirements.txt` but **no setup code** |
| Grafana | Deployed with datasources (Prometheus, Loki, Tempo) provisioned |
| Dashboards | **None** — empty `provisioning/dashboards/json/` directory |
| Logging | stdlib `logging` in both services; no structured output, no trace correlation |
| Metrics | No custom metrics; no `/metrics` endpoint on services |

---

## Target Architecture

```
┌──────────┐  ┌──────────────────┐
│   API    │  │ Stream Processor │
│(FastAPI) │  │    (Faust)       │
└────┬─────┘  └───────┬──────────┘
     │                │
     │  both import libs/observability
     │                │
     │  OTLP gRPC     │  OTLP gRPC
     │  (traces +     │  (traces +
     │   metrics +    │   metrics +
     │   logs)        │   logs)
     └───────┬────────┘
             ▼
      ┌─────────────┐
      │ OTel        │
      │ Collector   │
      └──┬───┬───┬──┘
         │   │   │
    ┌────┘   │   └────┐
    ▼        ▼        ▼
 ┌──────┐ ┌──────┐ ┌──────┐
 │Tempo │ │Prom  │ │Loki  │
 │traces│ │metric│ │ logs │
 └──┬───┘ └──┬───┘ └──┬───┘
    └────┬────┘        │
         ▼             │
      ┌────────────────┘
      ▼
  ┌────────┐
  │Grafana │  ← provisioned dashboards
  └────────┘
```

---

## Shared Code Strategy

All observability logic lives in a single shared package that both services install.

### Directory layout

```
libs/
└── observability/
    ├── pyproject.toml          # installable package
    └── observability/
        ├── __init__.py         # public API: init_telemetry, get_logger, metrics
        ├── telemetry.py        # OTel providers (traces, logs, metrics)
        ├── logging.py          # structlog config + trace-context processor
        └── metrics.py          # shared counters & histograms
```

### Package: `libs/observability/pyproject.toml`

```toml
[project]
name = "observability"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "opentelemetry-sdk>=1.28",
    "opentelemetry-exporter-otlp>=1.28",
    "structlog>=24.4",
]
```

### Module: `observability/telemetry.py`

Single `init_telemetry(service_name, otlp_endpoint)` function that sets up all three OTel signals:

```python
import logging

from opentelemetry import trace, metrics
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

from .logging import configure_structlog


def init_telemetry(service_name: str, otlp_endpoint: str) -> None:
    resource = Resource.create({"service.name": service_name})

    # traces
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=otlp_endpoint)
    ))
    trace.set_tracer_provider(tp)

    # logs
    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(BatchLogRecordProcessor(
        OTLPLogExporter(endpoint=otlp_endpoint)
    ))
    set_logger_provider(lp)
    logging.getLogger().addHandler(LoggingHandler(logger_provider=lp))

    # metrics
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=otlp_endpoint),
        export_interval_millis=10_000,
    )
    mp = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(mp)

    # structlog
    configure_structlog()
```

### Module: `observability/logging.py`

```python
import logging
import structlog
from opentelemetry import trace as oteltrace


def _add_otel_context(logger, method, event_dict):
    span = oteltrace.get_current_span()
    ctx = span.get_span_context()
    if ctx and ctx.trace_id:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def configure_structlog() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_otel_context,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
```

### Module: `observability/metrics.py`

Shared metric instruments — imported by both services.

```python
from opentelemetry import metrics

meter = metrics.get_meter("supplychain")

# Order counters
orders_received  = meter.create_counter("orders.received.total",  description="Orders received")
orders_validated = meter.create_counter("orders.validated.total", description="Orders validated")
orders_shipped   = meter.create_counter("orders.shipped.total",   description="Orders shipped")
orders_delivered = meter.create_counter("orders.delivered.total", description="Orders delivered")
orders_exception = meter.create_counter("orders.exception.total", description="Orders in exception")
orders_cancelled = meter.create_counter("orders.cancelled.total", description="Orders cancelled")

# Shipment counters
shipments_created   = meter.create_counter("shipments.created.total",   description="Shipments created")
shipments_delivered  = meter.create_counter("shipments.delivered.total", description="Shipments delivered")
shipments_exception  = meter.create_counter("shipments.exception.total",description="Shipments in exception")

# Histograms
pipeline_duration = meter.create_histogram(
    "order.pipeline.duration_ms",
    description="End-to-end order pipeline duration",
    unit="ms",
)
```

### Module: `observability/__init__.py`

```python
from .telemetry import init_telemetry
from .logging import configure_structlog
from .metrics import (
    orders_received, orders_validated, orders_shipped,
    orders_delivered, orders_exception, orders_cancelled,
    shipments_created, shipments_delivered, shipments_exception,
    pipeline_duration,
)

__all__ = [
    "init_telemetry", "configure_structlog",
    "orders_received", "orders_validated", "orders_shipped",
    "orders_delivered", "orders_exception", "orders_cancelled",
    "shipments_created", "shipments_delivered", "shipments_exception",
    "pipeline_duration",
]
```

### How services consume it

Both services add the shared lib to their `requirements.txt`:

```
# at the top of each requirements.txt
-e /libs/observability
```

Both Dockerfiles copy the shared lib before installing:

```dockerfile
FROM python:3.12-slim
WORKDIR /app

# shared lib first
COPY ../../libs /libs
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# ...
```

Since Docker `COPY` cannot escape the build context, the docker-compose build context
must be set to the project root and `dockerfile` pointed explicitly:

```yaml
# docker-compose.yml
api:
  build:
    context: .                          # project root
    dockerfile: services/api/Dockerfile
  # ...

stream-processor:
  build:
    context: .                              # project root
    dockerfile: services/stream_processor/Dockerfile
  # ...
```

Updated Dockerfiles (both follow the same pattern):

```dockerfile
# services/api/Dockerfile
FROM python:3.12-slim
WORKDIR /app

COPY libs/ /libs/
COPY services/api/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/api/ .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```dockerfile
# services/stream_processor/Dockerfile
FROM python:3.12-slim
WORKDIR /app

COPY libs/ /libs/
COPY services/stream_processor/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/stream_processor/ .

CMD ["faust", "-A", "app.main", "worker", "-l", "info"]
```

---

## Implementation Tasks

### Task 1 — Create `libs/observability` Package

Create the shared package as described above with these files:

| File | Purpose |
|------|---------|
| `libs/observability/pyproject.toml` | Package metadata and deps |
| `libs/observability/observability/__init__.py` | Public API re-exports |
| `libs/observability/observability/telemetry.py` | `init_telemetry()` — traces, logs, metrics providers |
| `libs/observability/observability/logging.py` | `configure_structlog()` + `_add_otel_context` processor |
| `libs/observability/observability/metrics.py` | Shared counters and histograms |

---

### Task 2 — Wire Shared Lib into API Service

**File: `services/api/app/telemetry.py`** — replace current contents:

```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from observability import init_telemetry
from app.config import settings


def setup_telemetry() -> None:
    init_telemetry(settings.otel_service_name, settings.otel_exporter_otlp_endpoint)

    from app.main import app  # noqa: C811
    FastAPIInstrumentor.instrument_app(app)
```

All telemetry, structlog, and metrics setup is delegated to the shared lib.  
The only API-specific line is `FastAPIInstrumentor`.

**File: `services/api/requirements.txt`** — add shared lib:

```
-e /libs/observability

# framework-specific instrumentations (remain here, not in shared lib)
opentelemetry-instrumentation-fastapi>=0.49b
opentelemetry-instrumentation-httpx>=0.49b
opentelemetry-instrumentation-sqlalchemy>=0.49b
opentelemetry-instrumentation-confluent-kafka>=0.49b
```

Remove duplicated top-level OTel deps (`opentelemetry-sdk`, `opentelemetry-exporter-otlp`)
since they come transitively from the shared lib.

---

### Task 3 — Wire Shared Lib into Stream Processor

**File: `services/stream_processor/app/telemetry.py`** — create new:

```python
from observability import init_telemetry
from app.config import settings


def setup_telemetry() -> None:
    init_telemetry(settings.otel_service_name, settings.otel_exporter_otlp_endpoint)
```

**File: `services/stream_processor/app/main.py`** — call on startup:

```python
import faust
from app.config import settings
from app.telemetry import setup_telemetry

setup_telemetry()

app = faust.App(
    "supplychain-stream-processor",
    broker=f"kafka://{settings.kafka_bootstrap_servers}",
    store="memory://",
    topic_partitions=4,
)

from app.agents import order_pipeline, shipment_tracker  # noqa: E402, F401
```

**File: `services/stream_processor/requirements.txt`** — add shared lib:

```
-e /libs/observability
```

Remove duplicated `opentelemetry-sdk`, `opentelemetry-exporter-otlp`.

---

### Task 4 — Add Tracing Spans to Stream Processor

The stream processor has zero tracing. Add manual spans using the standard `opentelemetry.trace` API (no shared-lib change needed — `trace.get_tracer()` works once `init_telemetry` has been called).

**File: `services/stream_processor/app/agents/order_pipeline.py`**:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

@app.agent(order_received_topic)
async def process_order(stream):
    async for event in stream:
        with tracer.start_as_current_span(
            "order.pipeline",
            attributes={"order.id": event.order_id},
        ):
            # existing pipeline logic — wrap each sub-step:
            ...
```

Wrap each sub-step in a child span:

```python
with tracer.start_as_current_span("order.validate", attributes={...}):
    ...
with tracer.start_as_current_span("order.erp_sync", attributes={...}):
    ...
with tracer.start_as_current_span("order.allocate", attributes={...}):
    ...
with tracer.start_as_current_span("order.ship", attributes={...}):
    ...
```

**File: `services/stream_processor/app/agents/shipment_tracker.py`**:

```python
with tracer.start_as_current_span(
    "shipment.track",
    attributes={"shipment.id": event.shipment_id, "shipment.status": event.status},
):
    ...
```

---

### Task 5 — Instrument Metrics in Application Code

Import counters/histograms from the shared lib — no local definitions needed.

**In `order_pipeline.py`**:

```python
import time
from observability import (
    orders_validated, orders_shipped, orders_exception, pipeline_duration,
)

start = time.monotonic()
# ... pipeline steps ...
pipeline_duration.record((time.monotonic() - start) * 1000, {"channel": event.channel})
orders_shipped.add(1, {"channel": event.channel, "carrier": carrier_result.carrier})
```

**In `shipment_tracker.py`**:

```python
from observability import shipments_delivered, shipments_exception

if new_status == "delivered":
    shipments_delivered.add(1, {"carrier": shipment.carrier})
elif new_status == "exception":
    shipments_exception.add(1, {"carrier": shipment.carrier})
```

**In API `routes/orders.py`**:

```python
from observability import orders_received

orders_received.add(1, {"channel": payload.channel})
```

---

### Task 6 — Replace `logging` with `structlog` in Application Code

Across both services, replace:

```python
import logging
logger = logging.getLogger(__name__)
logger.info("Pipeline started for order %s", order_id)
```

With:

```python
import structlog
logger = structlog.get_logger()
logger.info("pipeline_started", order_id=order_id)
```

`structlog` is configured once by the shared lib during `init_telemetry()`.  
Every log line automatically gets `trace_id`, `span_id`, timestamp, and level.

Key structured fields to include:

| Field | Where |
|-------|-------|
| `order_id` | All order pipeline logs |
| `shipment_id` | All shipment tracker logs |
| `status` | Status transition logs |
| `carrier` | Shipment logs |
| `channel` | Order receipt logs |
| `step` | Pipeline step (validate / erp / allocate / ship) |
| `error` | Exception logs |

This ensures Loki queries can filter by structured fields:

```
{service="stream-processor"} | json | order_id="abc-123"
```

---

### Task 7 — OTel Collector Config Update

**File: `infra/otel-collector/config.yaml`** — add resource and attribute processors:

```yaml
processors:
  batch:
    timeout: 5s
    send_batch_size: 1024
  resource:
    attributes:
      - key: deployment.environment
        value: dev
        action: upsert

exporters:
  loki:
    endpoint: http://loki:3100/loki/api/v1/push
    default_labels_enabled:
      exporter: false
      job: true
    labels:
      attributes:
        service.name: "service"
        log.level: "level"

  prometheusremotewrite:
    endpoint: http://prometheus:9090/api/v1/write
    resource_to_telemetry_conversion:
      enabled: true
```

Prometheus must be started with `--web.enable-remote-write-receiver` flag (see Task 9).

---

### Task 8 — Grafana Dashboards (Provisioned JSON)

Create dashboard JSON files under `infra/grafana/provisioning/dashboards/json/`.  
Docker volume already maps `./infra/grafana/provisioning` → `/etc/grafana/provisioning`.

#### Dashboard 1: `supply-chain-overview.json`

A single dashboard with the following rows/panels:

**Row 1 — Order KPIs (stat panels)**

| Panel | Type | Query (Prometheus) |
|-------|------|--------------------|
| Orders Received (24h) | Stat | `increase(orders_received_total[24h])` |
| Orders Shipped (24h) | Stat | `increase(orders_shipped_total[24h])` |
| Orders Delivered (24h) | Stat | `increase(orders_delivered_total[24h])` |
| Orders Exception (24h) | Stat (red) | `increase(orders_exception_total[24h])` |
| Avg Pipeline Duration | Stat | `rate(order_pipeline_duration_ms_sum[5m]) / rate(order_pipeline_duration_ms_count[5m])` |

**Row 2 — Order Status Breakdown (time-series + pie)**

| Panel | Type | Query |
|-------|------|-------|
| Orders Over Time | Time series | `rate(orders_received_total[5m])`, `rate(orders_shipped_total[5m])`, etc. stacked |
| Orders by Channel | Pie | `sum by (channel)(orders_received_total)` |
| Exceptions by Reason | Table | Loki: `{service="stream-processor"} |= "exception" \| json \| line_format "{{.reason}}"` |

**Row 3 — Shipment Status**

| Panel | Type | Query |
|-------|------|-------|
| Shipments Created vs Delivered | Time series | `rate(shipments_created_total[5m])`, `rate(shipments_delivered_total[5m])` |
| Shipments by Carrier | Bar gauge | `sum by (carrier)(shipments_created_total)` |
| Active Shipments (gauge) | Gauge | `shipments_created_total - shipments_delivered_total - shipments_exception_total` |

**Row 4 — Logs & Traces**

| Panel | Type | Query |
|-------|------|-------|
| Recent Errors | Logs (Loki) | `{service=~"api\|stream-processor"} \|= "ERROR"` |
| All Logs | Logs (Loki) | `{service=~"api\|stream-processor"}` with filter bar |
| Pipeline Traces | Tempo table | Service = `stream-processor`, operation = `order.pipeline` |

**Row 5 — Infrastructure**

| Panel | Type | Query |
|-------|------|-------|
| API Latency p50/p95/p99 | Time series | `histogram_quantile(0.95, rate(http_server_duration_ms_bucket{service="api"}[5m]))` |
| API Request Rate | Time series | `rate(http_server_active_requests{service="api"}[5m])` |
| Error Rate (5xx) | Stat (red) | `rate(http_server_duration_ms_count{http_status_code=~"5.."}[5m])` |

#### Dashboard 2: `order-detail.json` (optional drill-down)

Template variable: `$order_id`

| Panel | Type | Query |
|-------|------|-------|
| Order Event Timeline | Logs (Loki) | `{service=~".+"} \| json \| order_id="$order_id"` |
| Order Traces | Tempo search | attribute `order.id = $order_id` |

---

### Task 9 — Docker Compose Updates

```yaml
# Build contexts → project root so both services can COPY libs/
api:
  build:
    context: .
    dockerfile: services/api/Dockerfile

stream-processor:
  build:
    context: .
    dockerfile: services/stream_processor/Dockerfile

# Add Prometheus remote-write flag
prometheus:
  command:
    - --config.file=/etc/prometheus/prometheus.yml
    - --web.enable-remote-write-receiver

# Mount dashboard JSON folder
grafana:
  volumes:
    - ./infra/grafana/provisioning:/etc/grafana/provisioning
    - ./infra/grafana/provisioning/dashboards/json:/etc/grafana/provisioning/dashboards/json
    - grafana-data:/var/lib/grafana
```

---

## File Change Summary

| File | Action |
|------|--------|
| `libs/observability/pyproject.toml` | **Create**: shared package metadata |
| `libs/observability/observability/__init__.py` | **Create**: public API re-exports |
| `libs/observability/observability/telemetry.py` | **Create**: `init_telemetry()` — traces, logs, metrics |
| `libs/observability/observability/logging.py` | **Create**: structlog config + trace context processor |
| `libs/observability/observability/metrics.py` | **Create**: shared counters and histograms |
| `services/api/app/telemetry.py` | **Simplify**: delegate to `observability.init_telemetry()`, keep only `FastAPIInstrumentor` |
| `services/api/requirements.txt` | Add `-e /libs/observability`, remove redundant OTel deps |
| `services/api/Dockerfile` | Update `COPY` paths for project-root context, copy `libs/` |
| `services/stream_processor/app/telemetry.py` | **Create**: one-liner calling `observability.init_telemetry()` |
| `services/stream_processor/app/main.py` | Call `setup_telemetry()` at import time |
| `services/stream_processor/requirements.txt` | Add `-e /libs/observability`, remove redundant OTel deps |
| `services/stream_processor/Dockerfile` | Update `COPY` paths for project-root context, copy `libs/` |
| `services/stream_processor/app/agents/order_pipeline.py` | Add spans, `structlog`, import metrics from shared lib |
| `services/stream_processor/app/agents/shipment_tracker.py` | Add spans, `structlog`, import metrics from shared lib |
| `services/api/app/routes/orders.py` | Import `orders_received` from shared lib |
| `services/api/app/routes/shipments.py` | Import shipment counters from shared lib |
| `infra/otel-collector/config.yaml` | Add resource processor, Loki label config |
| `infra/grafana/provisioning/dashboards/json/supply-chain-overview.json` | **Create**: main dashboard |
| `infra/grafana/provisioning/dashboards/json/order-detail.json` | **Create**: drill-down dashboard |
| `docker-compose.yml` | Build context → root, Prometheus flag, Grafana volume |

---

## Verification Checklist

- [ ] `docker compose up -d` — all services healthy
- [ ] `from observability import init_telemetry` works in both containers
- [ ] API logs appear in Grafana → Explore → Loki (`{service="api"}`)
- [ ] Stream processor logs appear (`{service="stream-processor"}`)
- [ ] Logs contain `trace_id` and structured JSON fields
- [ ] Click `trace_id` in Loki → opens trace in Tempo
- [ ] Prometheus has metrics: `orders_received_total`, `shipments_created_total`, etc.
- [ ] Supply Chain Overview dashboard renders all panels
- [ ] Import an order via API → watch metrics increment and logs flow
- [ ] Pipeline trace shows child spans: validate → erp → allocate → ship
- [ ] Shipment status update → logs + metrics update in dashboard
