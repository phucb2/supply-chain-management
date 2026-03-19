# ML ETA Forecasting — Setup & Architecture

> Quick-start guide and architecture overview for the ML-powered ETA prediction feature.
> Reference this when onboarding, retraining, or debugging the ML pipeline.

---

## Architecture Overview

```
┌────────────┐   POST /orders   ┌─────┐  Kafka: order.*  ┌──────────────────┐
│  Test UI   │ ───────────────> │ API │ ───────────────> │ Stream Processor │
│ :8501      │                  │:8000│                  │ (Faust)          │
└────────────┘                  └─────┘                  └──────┬───────────┘
                                   │                           │
                                   │                  ┌────────┴────────┐
                                   │                  │                 │
                                   │          order_pipeline     eta_predictor
                                   │          (validate/ship)    (ML inference)
                                   │                  │                 │
                                   │                  │    shipment.created
                                   │                  │         │
                                   │                  │    Load model from
                                   │                  │    MLflow Registry
                                   │                  │         │
                                   │                  │    Predict ETA ──> Kafka: eta.predicted
                                   │                  │         │
                                   │                  │    Save to predictions table
                                   │                  │
                                   │          shipment_tracker
                                   │          (on delivered) ──> feedback loop
                                   │                  │          │
                                   ▼                  ▼          ▼
                              ┌──────────┐    ┌─────────────────────────┐
                              │PostgreSQL│    │ prediction_actuals table │
                              │  :5432   │    │ (actual vs predicted)    │
                              └──────────┘    └─────────────────────────┘

┌────────┐  artifacts   ┌───────┐   experiment tracking   ┌────────┐
│ MinIO  │ <──────────  │MLflow │  <────────────────────  │Training│
│ :9000  │  s3://ml-    │ :5001 │                         │ Script │
└────────┘  artifacts/  └───────┘                         └────────┘
```

### Key Components

| Component | Role |
|---|---|
| **API** (FastAPI, `:8000`) | REST gateway — accepts orders, exposes shipments and predictions |
| **Stream Processor** (Faust) | Three Kafka agents: `order_pipeline`, `eta_predictor`, `shipment_tracker` |
| **eta_predictor** agent | Consumes `shipment.created`, loads Production model from MLflow, predicts ETA, publishes `eta.predicted`, writes to `predictions` table |
| **shipment_tracker** agent | On `delivered` status, closes the feedback loop — computes actual ETA, stores error in `prediction_actuals` |
| **MLflow** (`:5001`) | Experiment tracking + model registry; backend on PostgreSQL, artifacts on MinIO (`s3://ml-artifacts/`) |
| **PostgreSQL** | Stores orders, shipments, `predictions`, `prediction_actuals` tables |
| **mlflow-init** service | One-shot bootstrap: registers `infra/mlflow/default-model/` into MLflow on first startup, promotes to Production |
| **MinIO** | S3-compatible object store for MLflow model artifacts |
| **Test UI** (Streamlit, `:8501`) | Interactive demo — creates orders, shows predictions, displays accuracy metrics |

### ML Tables

| Table | Purpose |
|---|---|
| `predictions` | Stores every ETA prediction: `shipment_id`, `predicted_eta_hours`, `model_version`, `input_features` (JSONB) |
| `prediction_actuals` | Feedback loop: `actual_eta_hours`, `absolute_error` per shipment, recorded on delivery |

### Model Features

| Feature | Source | Type |
|---|---|---|
| `carrier` | `shipments.carrier` | categorical |
| `channel` | `orders.channel` | categorical |
| `item_count` | `COUNT(order_items)` | numeric |
| `total_weight_kg` | `SUM(shipment_packages.weight)` | numeric |
| `day_of_week` | `shipments.created_at` | numeric (0–6) |
| `hour_of_day` | `shipments.created_at` | numeric (0–23) |

**Label:** `actual_eta_hours = delivered_at - created_at`

---

## Step-by-Step: Running the ML Pipeline

### Prerequisites

- Docker & Docker Compose installed
- `.env` file exists (copy from `.env.example` if missing)

### 1. Start Infrastructure

```bash
docker compose up -d
```

Wait until all services are healthy (especially `postgresql`, `kafka`, `mlflow`):

```bash
docker compose ps
```

On first startup, the `mlflow-init` service automatically registers a pre-trained default model
from `infra/mlflow/default-model/` into MLflow and promotes it to Production. This means the
`eta_predictor` agent can serve predictions immediately without manual training.

### 2. (Optional) Seed Training Data

The model needs delivered shipments to train on. If the database is fresh, seed synthetic data:

```bash
docker compose exec postgresql psql -U supplychain -d supplychain -f /dev/stdin < scripts/seed_training_data.sql
```

Verify data exists:

```bash
docker compose exec postgresql psql -U supplychain -d supplychain -c \
  "SELECT COUNT(*) FROM shipments WHERE status = 'delivered' AND delivered_at IS NOT NULL;"
```

You need at least ~20 rows.

### 3. (Optional) Retrain the Model

If you seeded new data or want to improve on the default model, copy the training script and run:

```bash
docker compose cp scripts/train_eta_model.py mlflow:/tmp/train_eta_model.py
docker compose exec mlflow python /tmp/train_eta_model.py
```

Expected output:

```
MLflow tracking URI: http://localhost:5001
Loaded 50 delivered shipments.
...
MAE    : XX.XX hours
RMSE   : XX.XX hours
Model registered as 'eta-model'.
```

### 4. Promote a New Model to Production

After retraining, promote the new version. Open MLflow UI at **http://localhost:5001**, or use the CLI:

```bash
docker compose exec mlflow python -c "
from mlflow.tracking import MlflowClient
c = MlflowClient()
mv = c.search_model_versions('name=\"eta-model\"')[0]
c.transition_model_version_stage('eta-model', mv.version, 'Production')
print(f'Version {mv.version} promoted to Production')
"
```

### 5. Restart the Stream Processor

The `eta_predictor` agent loads the model on startup, so restart it to pick up the new model:

```bash
docker compose restart stream-processor
```

Verify the model loaded:

```bash
docker compose logs stream-processor --tail 30 2>&1 | grep "ml_model_loaded"
```

### 6. Run a Demo

**Option A — Test UI** (recommended):

1. Open **http://localhost:8501**
2. Navigate to **ETA Predictions** → **Live Demo** tab
3. Click **Run Demo** — watches the full lifecycle with live progress

**Option B — simulate.py script:**

```bash
docker compose cp scripts/simulate.py api:/tmp/simulate.py
docker compose exec api python /tmp/simulate.py
```

### 7. Verify Predictions

Check the database directly:

```bash
docker compose exec postgresql psql -U supplychain -d supplychain -c \
  "SELECT shipment_id, predicted_eta_hours, model_version FROM predictions ORDER BY predicted_at DESC LIMIT 5;"
```

Check the feedback loop (after deliveries):

```bash
docker compose exec postgresql psql -U supplychain -d supplychain -c \
  "SELECT shipment_id, predicted_eta_hours, actual_eta_hours, absolute_error
   FROM prediction_actuals pa JOIN predictions p ON p.id = pa.prediction_id
   ORDER BY pa.recorded_at DESC LIMIT 5;"
```

Or use the **Test UI** → **ETA Predictions** → **Model Accuracy** tab.

---

## Retraining

When enough new delivered shipments accumulate, retrain by repeating steps 3–5. The training script automatically registers a new model version — just promote it and restart the stream processor.

## Observability

Three custom metrics are emitted via OpenTelemetry:

| Metric | Type | Description |
|---|---|---|
| `ml.predictions.total` | Counter | Total ETA predictions made |
| `ml.prediction.latency_seconds` | Histogram | Model inference latency |
| `ml.prediction.error_hours` | Histogram | Absolute error when feedback loop closes |

View these in **Grafana** at **http://localhost:3000** (Prometheus data source).

## Service Ports

| Service | Port |
|---|---|
| API | `localhost:8000` |
| Test UI | `localhost:8501` |
| MLflow | `localhost:5001` |
| MinIO Console | `localhost:9001` |
| Grafana | `localhost:3000` |
| Prometheus | `localhost:9090` |
| PostgreSQL | `localhost:5432` |
| Kafka | `localhost:9092` |
