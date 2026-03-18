"""MinIO storage — archive raw order payloads."""

import json
import logging
from datetime import datetime, timezone
from io import BytesIO

from minio import Minio

from app.config import settings

logger = logging.getLogger(__name__)

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
        logger.info("Archived payload to %s/%s", BUCKET, object_name)
        return object_name
    except Exception:
        logger.exception("Failed to archive payload for order %s", order_id)
        return None
