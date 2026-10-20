"""Trace correlation for structured logs.

Reads the active OpenTelemetry span context and exposes trace identifiers so
that every log line can be joined back to the distributed trace in Tempo.
``trace_id``/``span_id`` are ``None`` when no valid, sampled span context
exists - the fields are then explicitly rendered as ``null`` (never omitted
or faked) as required by docs/TELEMETRY_DESIGN.md.
"""

from __future__ import annotations

import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import SpanContext


def _current_span_context() -> SpanContext | None:
    span = trace.get_current_span()
    if span is None:
        return None
    ctx = span.get_span_context()
    if not ctx.is_valid:
        return None
    return ctx


def trace_correlation() -> dict[str, str | None]:
    """Return ``{"trace_id": ..., "span_id": ...}`` for the active span.

    Values are lowercase hex per the W3C Trace Context format, or ``None``
    when there is no valid (sampled) span context.
    """
    ctx = _current_span_context()
    if ctx is None or not ctx.trace_flags.sampled:
        # Not sampled: a trace exists but will not be stored in the backend.
        # We still emit the ids when the context is valid so local stdout
        # correlation works during development.
        if ctx is None:
            return {"trace_id": None, "span_id": None}
    return {
        "trace_id": format(ctx.trace_id, "032x") if ctx else None,
        "span_id": format(ctx.span_id, "016x") if ctx else None,
    }


class TraceCorrelationFilter(logging.Filter):
    """Inject ``trace_id``/``span_id`` into every ``LogRecord``."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        corr = trace_correlation()
        record.trace_id = corr["trace_id"]  # type: ignore[attr-defined]
        record.span_id = corr["span_id"]  # type: ignore[attr-defined]
        return True


def build_json_formatter() -> logging.Formatter:
    """Return a JSON formatter with trace correlation fields.

    Implemented here (rather than pulling a third-party JSON logger) so the
    log schema is a documented, testable contract.
    """
    import json
    from datetime import datetime, timezone

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:  # noqa: A003
            ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
            payload: dict[str, Any] = {
                "timestamp": ts,
                "level": record.levelname,
                "service": getattr(record, "service_name", None) or record.name,
                "logger": record.name,
                "message": record.getMessage(),
                "trace_id": getattr(record, "trace_id", None),
                "span_id": getattr(record, "span_id", None),
            }
            # Exception rendering: full stack trace on its own field.
            if record.exc_info:
                payload["exception"] = self.formatException(record.exc_info)
            return json.dumps(payload, ensure_ascii=False)

    return JsonFormatter()


def configure_logging(service_name: str, level: str = "INFO") -> None:
    """Configure root logging with the TraceForge JSON schema."""
    handler = logging.StreamHandler()
    handler.addFilter(TraceCorrelationFilter())
    formatter = build_json_formatter()
    # Attach service identity once at setup time.
    old_format = formatter.format

    def fmt(record: logging.LogRecord) -> str:  # noqa: ANN001
        record.service_name = service_name  # type: ignore[attr-defined]
        return old_format(record)

    handler.setFormatter(logging.Formatter())  # placeholder, replaced below
    handler.format = fmt  # type: ignore[method-assign]

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet the very chatty OTel exporter diagnostics by default.
    logging.getLogger("opentelemetry.exporter").setLevel(logging.WARNING)
