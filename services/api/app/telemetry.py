from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.config import settings
from observability import init_telemetry


def setup_telemetry() -> None:
    init_telemetry(settings.otel_service_name, settings.otel_exporter_otlp_endpoint)

    from app.main import app  # noqa: C811

    FastAPIInstrumentor.instrument_app(app)
