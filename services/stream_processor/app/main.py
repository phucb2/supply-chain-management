import faust

from app.config import settings
from app.telemetry import setup_telemetry

otel_handler = setup_telemetry()

app = faust.App(
    "supplychain-stream-processor",
    broker=f"kafka://{settings.kafka_bootstrap_servers}",
    store="memory://",
    topic_partitions=4,
    loghandlers=[otel_handler],
)

from app.agents import order_pipeline, shipment_tracker  # noqa: E402, F401
