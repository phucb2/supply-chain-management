"""ETA prediction agent: consumes shipment.created, predicts delivery ETA via ML model."""

import time
import uuid
from datetime import datetime, timezone

import structlog
from opentelemetry import trace

from app.main import app
from app.models import ShipmentCreated
from observability import ml_prediction_latency, ml_predictions_total

logger = structlog.get_logger()
tracer = trace.get_tracer(__name__)

shipment_created_topic = app.topic("shipment.created", value_type=ShipmentCreated)
eta_predicted_topic = app.topic("eta.predicted", value_serializer="json")

_model = None
_model_version = "unknown"

ETA_MIN_HOURS = 0.0
ETA_MAX_HOURS = 720.0
ETA_FALLBACK_HOURS = 48.0


@app.task
async def _load_model():
    """Load the production ETA model from MLflow on worker startup."""
    global _model, _model_version
    try:
        import mlflow

        from app.config import settings

        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        _model = mlflow.pyfunc.load_model("models:/eta-model/Production")
        _model_version = _model.metadata.run_id[:8] if _model.metadata.run_id else "prod"
        logger.info("ml_model_loaded", model_version=_model_version)
    except Exception:
        logger.warning("ml_model_load_failed", exc_info=True)
        _model = None


def _build_features(shipment, order) -> dict:
    """Build the feature dict from DB objects for model inference."""
    item_count = len(order.items) if order and order.items else 0
    total_weight = sum(
        (p.weight or 0.0) for p in (shipment.packages or [])
    )
    created = shipment.created_at or datetime.now(timezone.utc)

    return {
        "carrier": shipment.carrier or "unknown",
        "channel": order.channel if order else "unknown",
        "item_count": item_count,
        "total_weight_kg": total_weight,
        "day_of_week": created.weekday(),
        "hour_of_day": created.hour,
    }


CATEGORICAL_FEATURES = ["carrier", "channel"]


def _predict(features: dict) -> float:
    """Run model inference with sanity bounds."""
    import pandas as pd

    df = pd.DataFrame([features])
    for col in CATEGORICAL_FEATURES:
        if col in df.columns:
            df[col] = df[col].astype("category")
    raw_prediction = float(_model.predict(df)[0])

    if raw_prediction <= ETA_MIN_HOURS or raw_prediction > ETA_MAX_HOURS:
        logger.warning(
            "ml_prediction_out_of_bounds",
            raw=raw_prediction,
            fallback=ETA_FALLBACK_HOURS,
        )
        return ETA_FALLBACK_HOURS
    return round(raw_prediction, 2)


@app.agent(shipment_created_topic)
async def predict_eta(stream):
    async for event in stream:
        shipment_id = event.shipment_id

        with tracer.start_as_current_span(
            "ml.predict_eta", attributes={"shipment.id": shipment_id},
        ):
            if _model is None:
                logger.debug("ml_model_not_loaded", shipment_id=shipment_id)
                continue

            try:
                from app.db import get_shipment_with_order, save_prediction

                shipment, order = await get_shipment_with_order(uuid.UUID(shipment_id))
                if shipment is None:
                    logger.error("shipment_not_found_for_eta", shipment_id=shipment_id)
                    continue

                features = _build_features(shipment, order)

                start = time.monotonic()
                predicted_eta = _predict(features)
                latency = time.monotonic() - start

                ml_prediction_latency.record(latency)
                ml_predictions_total.add(1, {"model_version": _model_version})

                now = datetime.now(timezone.utc)
                await save_prediction(
                    shipment_id=shipment.id,
                    predicted_eta_hours=predicted_eta,
                    model_version=_model_version,
                    input_features=features,
                )

                await eta_predicted_topic.send(value={
                    "shipment_id": shipment_id,
                    "predicted_eta_hours": predicted_eta,
                    "model_version": _model_version,
                    "predicted_at": now.isoformat(),
                })

                logger.info(
                    "eta_predicted",
                    shipment_id=shipment_id,
                    predicted_eta_hours=predicted_eta,
                    model_version=_model_version,
                    latency_ms=round(latency * 1000, 1),
                )

            except Exception:
                logger.exception("eta_prediction_failed", shipment_id=shipment_id)
