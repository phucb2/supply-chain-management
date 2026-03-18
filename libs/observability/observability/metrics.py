from opentelemetry import metrics

meter = metrics.get_meter("supplychain")

# Order counters – names omit the "_total" suffix that Prometheus adds automatically for counters
orders_received = meter.create_counter(
    "orders.received", description="Orders received",
)
orders_validated = meter.create_counter(
    "orders.validated", description="Orders validated",
)
orders_shipped = meter.create_counter(
    "orders.shipped", description="Orders shipped",
)
orders_delivered = meter.create_counter(
    "orders.delivered", description="Orders delivered",
)
orders_exception = meter.create_counter(
    "orders.exception", description="Orders in exception",
)
orders_cancelled = meter.create_counter(
    "orders.cancelled", description="Orders cancelled",
)

# Shipment counters
shipments_created = meter.create_counter(
    "shipments.created", description="Shipments created",
)
shipments_delivered = meter.create_counter(
    "shipments.delivered", description="Shipments delivered",
)
shipments_exception = meter.create_counter(
    "shipments.exception", description="Shipments in exception",
)

# Histograms
pipeline_duration = meter.create_histogram(
    "order.pipeline.duration_ms",
    description="End-to-end order pipeline duration",
    unit="ms",
)
