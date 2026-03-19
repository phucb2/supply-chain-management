"""
Bootstrap the default ETA model into MLflow on first startup.
Skips if a model named 'eta-model' already exists.

Mounted at /tmp/init-mlflow-model.py and run by the mlflow-init service.
Expects the default model artifacts at /tmp/default-model/.
"""

import os
import sys
import time

import mlflow
from mlflow.tracking import MlflowClient

MODEL_NAME = "eta-model"
EXPERIMENT_NAME = "eta-forecasting"
MODEL_DIR = "/tmp/default-model"
MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001")

mlflow.set_tracking_uri(MLFLOW_URI)
client = MlflowClient()

existing = client.search_model_versions(f'name="{MODEL_NAME}"')
if existing:
    print(f"Model '{MODEL_NAME}' already has {len(existing)} version(s). Skipping init.")
    sys.exit(0)

print(f"No existing model '{MODEL_NAME}' found. Registering default model...")

mlflow.set_experiment(EXPERIMENT_NAME)

with mlflow.start_run(run_name="default-init") as run:
    mlflow.log_param("source", "infra-bootstrap")
    mlflow.log_param("note", "Pre-trained default model loaded from infra/mlflow/default-model")
    mlflow.lightgbm.log_model(
        lgb_model=mlflow.lightgbm.load_model(MODEL_DIR),
        artifact_path="model",
        registered_model_name=MODEL_NAME,
    )
    print(f"Registered run {run.info.run_id}")

time.sleep(2)

versions = client.search_model_versions(f'name="{MODEL_NAME}"')
if versions:
    v = versions[0]
    client.transition_model_version_stage(MODEL_NAME, v.version, "Production")
    print(f"Promoted {MODEL_NAME} v{v.version} to Production.")
else:
    print("WARNING: Model registered but no versions found.")
    sys.exit(1)

print("MLflow model init complete.")
