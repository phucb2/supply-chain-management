import json

import structlog
from confluent_kafka import Producer

from app.config import settings

logger = structlog.get_logger()

_producer: Producer | None = None


def get_producer() -> Producer:
    global _producer
    if _producer is None:
        _producer = Producer({
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "enable.idempotence": True,
            "acks": "all",
        })
    return _producer


def _delivery_callback(err, msg):
    if err:
        logger.error("kafka_delivery_failed", error=str(err))
    else:
        logger.debug("kafka_delivered", topic=msg.topic(), partition=msg.partition(), offset=msg.offset())


def publish_event(topic: str, key: str, value: dict) -> None:
    producer = get_producer()
    producer.produce(
        topic=topic,
        key=key,
        value=json.dumps(value),
        callback=_delivery_callback,
    )
    producer.poll(0)
