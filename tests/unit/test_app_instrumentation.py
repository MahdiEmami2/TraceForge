"""Unit tests for FastAPI route instrumentation and HTTP behavior.

Uses FastAPI's TestClient (in-process ASGI) against the *real* app factory.
A single session-scoped TracerProvider with an in-memory exporter captures
spans for every app created in this module - this mirrors production, where
the global OTel provider is set exactly once per process.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from traceforge.core.app_factory import create_app
from traceforge.core.config import ServiceConfig
from traceforge.core.detector import ThresholdDetector
from traceforge.core.scenarios import ScenarioRunner
from traceforge.inventory.main import build_router as inventory_router


@pytest.fixture(scope="module")
def spans() -> InMemorySpanExporter:
    """One provider per module; business tracers resolve against it globally."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace._set_tracer_provider(provider, log=False)  # type: ignore[attr-defined]
    return exporter


def _config(**overrides: object) -> ServiceConfig:
    values: dict[str, object] = {
        "service_name": "inventory-service",
        "environment": "development",
        "otel_export_enabled": False,
        "otel_exporter_endpoint": "http://otel-collector:4318/v1/traces",
    }
    values.update(overrides)
    config = ServiceConfig(**values)  # type: ignore[arg-type]
    config.validate_config()
    return config


def _client(
    spans: InMemorySpanExporter,
    provider: TracerProvider | None = None,
    **config_overrides: object,
) -> TestClient:
    app = create_app(
        "inventory-service",
        config=_config(**config_overrides),
        extra_routers={"": inventory_router(ScenarioRunner())},
        tracer_provider=provider,
    )
    app.state.scenario_override = None
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def clean_spans(spans: InMemorySpanExporter) -> InMemorySpanExporter:
    spans.clear()
    return spans


def test_health_and_readiness(clean_spans: InMemorySpanExporter) -> None:
    client = _client(clean_spans)
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["service"] == "inventory-service"
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["ready"] is True


def test_metrics_endpoint_serves_prometheus_text(clean_spans: InMemorySpanExporter) -> None:
    client = _client(clean_spans)
    client.get("/inventory", params={"sku": "SKU-1"})
    body = client.get("/metrics").text
    assert "tf_http_requests_total" in body
    assert "tf_http_request_duration_seconds" in body


def test_unknown_sku_returns_404(clean_spans: InMemorySpanExporter) -> None:
    client = _client(clean_spans)
    resp = client.get("/inventory", params={"sku": "NOPE"})
    assert resp.status_code == 404


def test_healthz_excluded_from_request_metrics(clean_spans: InMemorySpanExporter) -> None:
    client = _client(clean_spans)
    client.get("/healthz")
    body = client.get("/metrics").text
    assert "# TYPE tf_http_requests_total counter" in body
    assert "/healthz" not in body


def test_successful_request_creates_server_span(clean_spans: InMemorySpanExporter) -> None:
    client = _client(clean_spans)
    resp = client.get("/inventory", params={"sku": "SKU-1"})
    assert resp.status_code == 200
    span_names = [s.name for s in clean_spans.get_finished_spans()]
    assert any("inventory.lookup" in name for name in span_names)


def test_scenario_error_propagates_as_503(clean_spans: InMemorySpanExporter) -> None:
    client = _client(clean_spans)
    client.post("/inventory/scenario", json={"scenario": "error"})
    resp = client.get("/inventory", params={"sku": "SKU-1"})
    assert resp.status_code == 503


def test_scenario_exception_recorded_on_span(clean_spans: InMemorySpanExporter) -> None:
    client = _client(clean_spans)
    client.post("/inventory/scenario", json={"scenario": "exception"})
    resp = client.get("/inventory", params={"sku": "SKU-1"})
    assert resp.status_code == 500
    names = [s.name for s in clean_spans.get_finished_spans()]
    assert any("inventory.lookup" in n for n in names)


def test_slow_scenario_takes_configured_time(clean_spans: InMemorySpanExporter) -> None:
    client = _client(clean_spans, slow_delay_ms=150)
    client.post("/inventory/scenario", json={"scenario": "slow"})
    start = time.perf_counter()
    resp = client.get("/inventory", params={"sku": "SKU-1"})
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert resp.status_code == 200
    assert elapsed_ms >= 140


def test_threshold_scenario_crosses_detector(clean_spans: InMemorySpanExporter) -> None:
    """The threshold scenario must produce a duration the detector flags."""
    client = _client(clean_spans, latency_threshold_ms=500)
    client.post("/inventory/scenario", json={"scenario": "threshold"})
    client.get("/inventory", params={"sku": "SKU-1"})
    spans_list = clean_spans.get_finished_spans()
    lookup = next(s for s in spans_list if "inventory.lookup" in s.name)
    duration_ms = (lookup.end_time - lookup.start_time) / 1_000_000
    verdict = ThresholdDetector(500).classify(duration_ms)
    assert verdict.is_breach is True


def test_safety_headers_present(clean_spans: InMemorySpanExporter) -> None:
    client = _client(clean_spans)
    resp = client.get("/healthz")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_metrics_survive_collector_outage(clean_spans: InMemorySpanExporter) -> None:
    """With export disabled (simulated collector outage) the app still serves."""
    client = _client(clean_spans, otel_export_enabled=False)
    assert client.get("/healthz").status_code == 200
