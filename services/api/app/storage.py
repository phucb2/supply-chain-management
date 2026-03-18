"""MinIO storage — archive raw order payloads."""

import json
from datetime import datetime, timezone
from io import BytesIO

import structlog
from minio import Minio

from app.config import settings

logger = structlog.get_logger()

_client: Minio | None = None

BUCKET = "raw-payloads"


def _get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False,
        )
    return _client


def upload_raw_payload(order_id: str, payload: dict) -> str | None:
    """Write raw payload to MinIO. Returns object name on success, None on failure."""
    try:
        client = _get_client()
        date_prefix = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        object_name = f"{date_prefix}/{order_id}.json"
        data = json.dumps(payload).encode()
        client.put_object(
            BUCKET,
            object_name,
            BytesIO(data),
            length=len(data),
            content_type="application/json",
        )
        logger.info("payload_archived", bucket=BUCKET, object_name=object_name)
        return object_name
    except Exception:
        logger.exception("payload_archive_failed", order_id=order_id)
        return None
