import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_logger = logging.getLogger(__name__)


def configure_telemetry() -> None:
    # TODO: implement (hint: Resource.create({SERVICE_NAME: "payment-ledger-api"}))
    # TODO: implement (hint: OTLPSpanExporter(endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")))
    # TODO: implement (hint: TracerProvider(resource=...) → add_span_processor(BatchSpanProcessor(...)) → trace.set_tracer_provider(...))
    pass
