import logging

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .logging import configure_structlog


def init_telemetry(service_name: str, otlp_endpoint: str) -> LoggingHandler:
    """Set up OTel traces, logs, metrics and structlog. Returns the LoggingHandler
    so callers can pass it to frameworks (e.g. Faust loghandlers) that reset
    the root logger."""
    resource = Resource.create({"service.name": service_name})

    # traces
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=otlp_endpoint)
    ))
    trace.set_tracer_provider(tp)

    # logs
    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(BatchLogRecordProcessor(
        OTLPLogExporter(endpoint=otlp_endpoint)
    ))
    set_logger_provider(lp)
    handler = LoggingHandler(logger_provider=lp, level=logging.INFO)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    # metrics
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=otlp_endpoint),
        export_interval_millis=10_000,
    )
    mp = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(mp)

    # structlog
    configure_structlog()

    return handler
