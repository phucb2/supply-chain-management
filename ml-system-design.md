System design for **ETA forecasting** — batch training + streaming inference (R9, R10).

## 1. Goal

* Train an ETA prediction model on historical shipment data (batch, R9)
* Serve real-time ETA predictions when new shipments are created (streaming, R10)

Flow:

**PostgreSQL → Python training script → MLflow → Faust worker (Kafka) → `eta.predicted` topic**

---

## 2. High-level architecture

```text
                        BATCH (offline)                          STREAMING (online)
               ┌─────────────────────────────┐        ┌──────────────────────────────────┐
               │                             │        │                                  │
+------------+ │  +----------+  +---------+  │        │  +----------------+  +--------+  │
| PostgreSQL |───>| Training |─>| MLflow  |  │        │  | Faust Worker   |─>| Kafka  |  │
| (shipments)|    | Script   |  | (MinIO) |──────────────>| (inference)    |  | eta.   |  │
+------------+ │  +----------+  +---------+  │        │  +----------------+  |predicted| │
               │       │                     │        │        ↑             +--------+  │
               │       │ logs experiments,   │        │        │ consumes                │
               │       │ registers model     │        │        │                         │
               └───────┼─────────────────────┘        │  +-----+------+                  │
                       │                              │  | Kafka      |                  │
                       │                              │  | shipment.  |                  │
                       │                              │  | created    |                  │
                       │                              │  +------------+                  │
                       │                              └──────────────────────────────────┘
                       v
               +--------------+
               | Grafana      |
               | (metrics)    |
               +--------------+
```

**Key highlight:** training and inference are fully decoupled. The training pipeline produces a model artifact; the streaming worker loads it independently. They share no runtime.

---

## 3. Components

### A. Training pipeline (batch)

A Python script (or notebook) that runs on a schedule or manually.

Steps:

1. Query PostgreSQL for completed shipments with known actual delivery times
2. Build features from the data
3. Train a model (scikit-learn or LightGBM)
4. Log experiment to MLflow (metrics, parameters, model artifact)
5. If the model improves on the previous version, register it in MLflow Model Registry

Features used:

| Feature                 | Source                              | Type        |
| ----------------------- | ----------------------------------- | ----------- |
| `carrier`               | shipments.carrier                   | categorical |
| `channel`               | orders.channel                      | categorical |
| `item_count`            | COUNT(order_items)                  | numeric     |
| `total_weight_kg`       | SUM(shipment_packages.weight)       | numeric     |
| `day_of_week`           | shipments.created_at                | numeric     |
| `hour_of_day`           | shipments.created_at                | numeric     |
| **`actual_eta_hours`**  | computed (delivered_at - created_at) | **label** |

Why LightGBM / scikit-learn:

* tabular data — tree models outperform neural nets here
* fast to train (seconds/minutes, no GPU)
* small model file (KBs–MBs) — easy to load in a stream worker
* interpretable feature importance for debugging

**Key highlight:** MLflow tracks every training run (hyperparameters, metrics, artifacts). The Model Registry provides versioning and a clear `Staging → Production` promotion workflow, stored on MinIO.

---

### B. MLflow + MinIO (model registry & artifact store)

MLflow serves two purposes:

* **Experiment tracking** — compare training runs side by side
* **Model Registry** — version models with lifecycle stages

Artifacts (trained model files) are stored in MinIO under `s3://ml-artifacts/`. MLflow metadata (runs, metrics) is stored in PostgreSQL.

```text
MLflow UI
├── Experiments
│   └── eta-forecasting
│       ├── Run 1  (MAE: 5.2h, RMSE: 7.1h)  ← archived
│       ├── Run 2  (MAE: 4.8h, RMSE: 6.3h)  ← production
│       └── Run 3  (MAE: 4.5h, RMSE: 6.0h)  ← staging
└── Model Registry
    └── eta-model
        ├── v1 → archived
        ├── v2 → production  ← currently served
        └── v3 → staging     ← under evaluation
```

---

### C. Streaming inference (Faust worker)

A Faust (Python Kafka Streams) worker that:

1. Consumes `shipment.created` events from Kafka
2. Extracts features from the event payload
3. Runs the loaded model to predict ETA
4. Publishes the prediction to `eta.predicted` topic

Model loading:

* On startup, downloads the latest `Production` model from MLflow/MinIO
* Model is held in memory — inference is a single `model.predict()` call
* To update the model, restart the worker (it pulls the latest version)

```text
Input event (shipment.created):
{
  "shipment_id": "SH-1234",
  "carrier_id": "CARRIER-A",
  "origin_warehouse_id": "WH-01",
  "destination_region": "CENTRAL",
  "total_weight_kg": 8.5,
  "item_count": 2,
  "created_at": "2026-03-18T14:30:00Z"
}

Output event (eta.predicted):
{
  "shipment_id": "SH-1234",
  "predicted_eta_hours": 36.4,
  "model_version": "v2",
  "predicted_at": "2026-03-18T14:30:01Z"
}
```

**Key highlight:** Faust is a Python library (no JVM), fits the existing Python/FastAPI stack, and integrates with Kafka natively. The model runs in-process — no separate serving infrastructure needed.

---

### D. Prediction logging (feedback loop)

Predictions are stored in PostgreSQL so they can be compared to actuals later.

When a shipment reaches `DELIVERED`:

* look up the prediction for that `shipment_id`
* compute error: `|predicted_eta - actual_eta|`
* store the result

This closed loop provides ground truth for the next training cycle:

```text
Train model → Deploy → Predict → Ship delivers → Measure error → Retrain
```

Without this, the model degrades silently and there is no way to know.

---

## 4. Data flow summary

### Batch training (offline, scheduled)

```text
PostgreSQL ──(SQL query)──> pandas DataFrame
    ──(feature engineering)──> X_train, y_train
    ──(LightGBM.fit)──> trained model
    ──(mlflow.log_model)──> MLflow / MinIO
```

### Streaming inference (online, continuous)

```text
Kafka [shipment.created] ──> Faust worker
    ──(extract features from event)──> feature vector
    ──(model.predict)──> predicted ETA
    ──> Kafka [eta.predicted]
    ──> PostgreSQL [predictions table]
```

---

## 5. Database tables

### predictions

| Column              | Type      |
| ------------------- | --------- |
| id                  | UUID PK   |
| shipment_id         | UUID FK   |
| predicted_eta_hours | float     |
| model_version       | varchar   |
| input_features      | jsonb     |
| predicted_at        | timestamp |

### prediction_actuals

| Column              | Type      |
| ------------------- | --------- |
| id                  | UUID PK   |
| shipment_id         | UUID FK   |
| prediction_id       | UUID FK   |
| actual_eta_hours    | float     |
| absolute_error      | float     |
| recorded_at         | timestamp |

These two tables are sufficient. MLflow handles model metadata and training run history internally.

---

## 6. Kafka topics

| Topic                    | Producer           | Consumer             |
| ------------------------ | ------------------ | -------------------- |
| `shipment.created`       | Shipment Service   | Faust inference worker |
| `eta.predicted`          | Faust worker       | Notification / Dashboard |

Reuses existing `shipment.created` topic — no new topics needed except `eta.predicted`.

---

## 7. Key design decisions

### Batch training + streaming inference separation

Training needs bulk data and can take minutes. Inference needs to respond in milliseconds per event. Coupling them would compromise both. The model artifact file is the only contract between the two.

### MLflow over custom tracking

MLflow provides experiment comparison, model versioning, and a UI out of the box. Building this from scratch adds no value for the assignment.

### Faust over JVM Kafka Streams

The rest of the platform is Python/FastAPI. Faust keeps the entire ML pipeline in Python — training, feature engineering, and inference all share the same language and libraries.

### Tree model over deep learning

Tabular supply chain data (carrier, weight, region, time) is best served by gradient boosted trees. No GPU, fast training, small artifact, interpretable results.

### Prediction logging for feedback loop

Most ML demos skip this. Logging predictions and joining with actuals demonstrates understanding of production ML — models need continuous validation, not just one-time training.

---

## 8. Failure handling

| Failure                  | Mitigation                                          |
| ------------------------ | --------------------------------------------------- |
| MLflow / MinIO down      | Faust worker keeps cached model in memory, serves predictions normally |
| Training fails           | Previous production model stays active, no impact on inference |
| Invalid prediction       | Sanity check (ETA must be > 0 and < 720h), fallback to route average |
| Faust worker crashes     | Kafka consumer group rebalances, other instances pick up partitions |

---

## 9. Observability

Reuses the existing Prometheus + Grafana stack.

Metrics exposed:

* `ml_predictions_total` — prediction count (counter)
* `ml_prediction_latency_seconds` — inference time (histogram)
* `ml_prediction_error_hours` — |predicted - actual| when delivery completes (gauge)
* `ml_model_version` — currently loaded model version (info metric)

One Grafana dashboard showing prediction volume, latency, and accuracy over time is sufficient for the assignment scope.

---
