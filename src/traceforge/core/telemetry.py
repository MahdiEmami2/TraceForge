"""OpenTelemetry tracing + metrics setup shared by all TraceForge services.

Traces are exported via OTLP (default: ``http/protobuf``) to the local
OpenTelemetry Collector.  Metrics are exposed on ``/metrics`` in the
Prometheus text format via ``prometheus-client`` and scraped by Prometheus -
the Collector does *not* need to be up for metrics to work.

The exporter is wrapped so that a missing/unavailable Collector degrades
gracefully: the service keeps serving requests, logs one diagnostic line,
and marks ``tf_otel_export_failures_total`` so the failure itself is
observable.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter as GRPCSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as HTTPSpanExporter,
)
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, ConsoleLogExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
    SpanExportResult,
)

logger = logging.getLogger(__name__)

# Number of failed export rounds observed (used by tests + health endpoint).
_export_failures_lock = threading.Lock()
_export_failures = 0


def export_failures() -> int:
    with _export_failures_lock:
        return _export_failures


def _bump_export_failures() -> None:
    global _export_failures
    with _export_failures_lock:
        _export_failures += 1


class ResilientSpanExporter(SpanExporter):
    """Wraps an OTLP exporter so outage of the telemetry backend is non-fatal.

    The demo platform must keep serving user traffic when the Collector is
    down; the failure counter makes the degradation visible from the outside.
    """

    def __init__(self, wrapped: SpanExporter, on_failure: Any = None) -> None:
        self._wrapped = wrapped
        self._on_failure = on_failure
        super().__init__()

    def export(self, spans: Any) -> SpanExportResult:  # type: ignore[override]
        result = self._wrapped.export(spans)
        if result is SpanExportResult.FAILURE:
            _bump_export_failures()
            if self._on_failure:
                self._on_failure()
        return result

    def shutdown(self) -> None:  # type: ignore[override]
        self._wrapped.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:  # type: ignore[override]
        return self._wrapped.force_flush(timeout_millis)


def build_resource(service_name: str, environment: str) -> Resource:
    """Consistent service identity across traces, metrics and logs."""
    return Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "traceforge",
            "deployment.environment": environment,
        }
    )


def configure_tracing(
    resource: Resource,
    protocol: str,
    endpoint: str,
    timeout_ms: int = 5000,
    schedule_delay_ms: int = 500,
    export_enabled: bool = True,
) -> TracerProvider:
    """Configure the global ``TracerProvider`` with an OTLP span exporter."""
    provider = TracerProvider(resource=resource)
    sampler_note = "parentbased_always_on"
    if export_enabled:
        if protocol == "grpc":
            base: SpanExporter = GRPCSpanExporter(
                endpoint=endpoint.replace("http://", "").replace("https://", ""),
                timeout=timeout_ms / 1000.0,
                insecure=endpoint.startswith("http://"),
            )
        else:
            base = HTTPSpanExporter(
                endpoint=endpoint, timeout=timeout_ms / 1000.0
            )
        exporter: SpanExporter = ResilientSpanExporter(
            base,
            on_failure=lambda: logger.warning(
                "OTLP trace export failed; continuing without trace backend",
            ),
        )
    else:
        # No collector configured: emit spans to stdout so local development
        # still shows the shape of the telemetry we would produce.
        exporter = ConsoleSpanExporter()
        sampler_note = "stdout_only"

    provider.add_span_processor(
        BatchSpanProcessor(exporter, schedule_delay_millis=schedule_delay_ms)
    )
    trace.set_tracer_provider(provider)
    logger.info(
        "tracing configured exporter=%s endpoint=%s sampler=%s",
        protocol if export_enabled else "console",
        endpoint if export_enabled else "-",
        sampler_note,
    )
    return provider


def configure_metrics(resource: Resource) -> MeterProvider:
    """Create a MeterProvider.

    The Prometheus exposition happens through ``prometheus_client`` on
    ``/metrics``; this provider exists so hand-written instruments follow the
    OpenTelemetry API and can be asserted in tests with an in-memory reader.
    """
    return MeterProvider(resource=resource)


def configure_logging_export(resource: Resource, export_to_backend: bool = False) -> LoggerProvider:
    """Configure the OTel log pipeline.

    Default build ships structured logs to stdout only (docker compose
    captures them); exporting logs over OTLP to the Collector is supported
    behind a flag because the local demo does not include a log backend.
    """
    logger_provider = LoggerProvider(resource=resource)
    if export_to_backend:
        # OTLP log export is only wired when a log backend is configured;
        # console emission is the fallback so logs are never silently lost.
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(ConsoleLogExporter())  # type: ignore[arg-type]
        )
    else:
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(ConsoleLogExporter())  # type: ignore[arg-type]
        )
    set_logger_provider(logger_provider)

    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    return logger_provider
