"""Unit tests for trace-correlated structured logging."""

from __future__ import annotations

import json
import logging

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from traceforge.core.logging_setup import (
    TraceCorrelationFilter,
    build_json_formatter,
    trace_correlation,
)


@pytest.fixture()
def provider_with_memory() -> tuple[TracerProvider, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider, exporter


def test_correlation_fields_absent_without_span() -> None:
    corr = trace_correlation()
    assert corr == {"trace_id": None, "span_id": None}


def test_json_log_contains_real_trace_id(provider_with_memory: tuple) -> None:
    _, _ = provider_with_memory
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("op") as span:
        ctx = span.get_span_context()
        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1, "hello", None, None
        )
        assert TraceCorrelationFilter().filter(record) is True
        payload = json.loads(build_json_formatter().format(record))
        assert payload["trace_id"] == format(ctx.trace_id, "032x")
        assert payload["span_id"] == format(ctx.span_id, "016x")


def test_json_log_null_ids_without_context() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", None, None)
    assert TraceCorrelationFilter().filter(record) is True
    payload = json.loads(build_json_formatter().format(record))
    assert payload["trace_id"] is None
    assert payload["span_id"] is None


def test_exception_rendered_with_stack(provider_with_memory: tuple) -> None:
    _, _ = provider_with_memory
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    TraceCorrelationFilter().filter(record)
    payload = json.loads(build_json_formatter().format(record))
    assert "ValueError: boom" in payload["exception"]
    assert "Traceback" in payload["exception"]


def test_sensitive_values_not_in_log_schema() -> None:
    """The JSON schema never includes headers or payloads - only fixed keys."""
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    TraceCorrelationFilter().filter(record)
    payload = build_json_formatter().format(record)
    for forbidden in ("authorization", "cookie", "password"):
        assert forbidden not in payload
