from app.config import settings
from observability import init_telemetry


def setup_telemetry():
    return init_telemetry(settings.otel_service_name, settings.otel_exporter_otlp_endpoint)
