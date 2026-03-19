"""
Batch ETA model training script.
Queries PostgreSQL for delivered shipments, trains a LightGBM regressor,
logs the experiment to MLflow, and registers the model.

Usage:
    python scripts/train_eta_model.py

Env vars (or defaults):
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
    MLFLOW_TRACKING_URI, MLFLOW_S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
"""

import os
import sys

import lightgbm as lgb
import mlflow
import mlflow.lightgbm
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sqlalchemy import create_engine, text

EXPERIMENT_NAME = "eta-forecasting"
MODEL_NAME = "eta-model"
CATEGORICAL_FEATURES = ["carrier", "channel"]

FEATURE_QUERY = text("""
    SELECT
        s.id            AS shipment_id,
        s.carrier,
        o.channel,
        s.created_at    AS ship_created_at,
        s.delivered_at,
        COUNT(oi.id)    AS item_count,
        COALESCE(SUM(sp.weight), 0) AS total_weight_kg
    FROM shipments s
    JOIN orders o       ON o.id = s.order_id
    LEFT JOIN order_items oi ON oi.order_id = o.id
    LEFT JOIN shipment_packages sp ON sp.shipment_id = s.id
    WHERE s.status = 'delivered'
      AND s.delivered_at IS NOT NULL
    GROUP BY s.id, s.carrier, o.channel, s.created_at, s.delivered_at
""")


def get_database_url() -> str:
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "supplychain")
    user = os.getenv("POSTGRES_USER", "supplychain")
    password = os.getenv("POSTGRES_PASSWORD", "supplychain_secret")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def load_data() -> pd.DataFrame:
    engine = create_engine(get_database_url())
    with engine.connect() as conn:
        df = pd.read_sql(FEATURE_QUERY, conn)
    engine.dispose()
    return df


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df["actual_eta_hours"] = (
        df["delivered_at"] - df["ship_created_at"]
    ).dt.total_seconds() / 3600

    df["day_of_week"] = df["ship_created_at"].dt.dayofweek
    df["hour_of_day"] = df["ship_created_at"].dt.hour

    df = df.drop(columns=["shipment_id", "ship_created_at", "delivered_at"])

    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype("category")

    return df


def train(df: pd.DataFrame) -> dict:
    y = df["actual_eta_hours"]
    X = df.drop(columns=["actual_eta_hours"])

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42,
    )

    params = {
        "objective": "regression",
        "metric": "mae",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "verbose": -1,
    }

    train_set = lgb.Dataset(X_train, label=y_train, categorical_feature=CATEGORICAL_FEATURES)
    val_set = lgb.Dataset(X_test, label=y_test, reference=train_set, categorical_feature=CATEGORICAL_FEATURES)

    model = lgb.train(
        params,
        train_set,
        num_boost_round=500,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)],
    )

    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = root_mean_squared_error(y_test, y_pred)

    return {"model": model, "mae": mae, "rmse": rmse, "params": params, "n_samples": len(df)}


def main():
    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001")
    mlflow.set_tracking_uri(mlflow_uri)

    print(f"MLflow tracking URI: {mlflow_uri}")
    print("Loading data from PostgreSQL...")

    df = load_data()
    if df.empty:
        print("No delivered shipments found. Nothing to train on.")
        sys.exit(0)

    print(f"Loaded {len(df)} delivered shipments.")
    df = engineer_features(df)

    mlflow.set_experiment(EXPERIMENT_NAME)

    with mlflow.start_run() as run:
        result = train(df)

        mlflow.log_params(result["params"])
        mlflow.log_params({"n_samples": result["n_samples"]})
        mlflow.log_metric("mae", result["mae"])
        mlflow.log_metric("rmse", result["rmse"])

        mlflow.lightgbm.log_model(
            result["model"],
            artifact_path="model",
            registered_model_name=MODEL_NAME,
        )

        print(f"\nRun ID : {run.info.run_id}")
        print(f"MAE    : {result['mae']:.2f} hours")
        print(f"RMSE   : {result['rmse']:.2f} hours")
        print(f"Model registered as '{MODEL_NAME}'.")


if __name__ == "__main__":
    main()
