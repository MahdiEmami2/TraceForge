"""Unit tests for metric creation, label discipline and redaction."""

from __future__ import annotations

from prometheus_client import CollectorRegistry

from traceforge.core.middleware import (
    MetricsState,
    counter_snapshot,
    redact_headers,
)


def test_request_metrics_created_with_bounded_labels() -> None:
    state = MetricsState("test-svc", registry=CollectorRegistry())
    state.observe_request("GET", "/orders/{order_id}", 200, 0.02)
    snapshot = counter_snapshot(state.requests_total)
    assert ("test-svc", "GET", "/orders/{order_id}", "200") in snapshot
    assert snapshot[("test-svc", "GET", "/orders/{order_id}", "200")] == 1.0


def test_error_metric_counts_5xx_only() -> None:
    state = MetricsState("test-svc", registry=CollectorRegistry())
    state.observe_request("GET", "/x", 200, 0.01)
    state.observe_request("GET", "/x", 503, 0.01)
    errors = counter_snapshot(state.request_errors_total)
    assert sum(errors.values()) == 1.0


def test_latency_breach_counter_increments_above_threshold() -> None:
    state = MetricsState("test-svc", registry=CollectorRegistry())
    state.latency_threshold_s = 1.0
    state.observe_request("GET", "/x", 200, 1.5)
    state.observe_request("GET", "/x", 200, 0.5)
    breaches = counter_snapshot(state.latency_threshold_breaches_total)
    assert sum(breaches.values()) == 1.0


def test_downstream_failure_metric_kinds() -> None:
    state = MetricsState("order-svc", registry=CollectorRegistry())
    state.observe_downstream_failure("inventory-service", "ConnectError")
    failures = counter_snapshot(state.downstream_failures_total)
    assert ("order-svc", "inventory-service", "ConnectError") in failures


def test_route_template_resolution() -> None:
    from fastapi import FastAPI

    from traceforge.core.middleware import route_template

    app = FastAPI()

    @app.get("/orders/{order_id}")
    async def order(order_id: str) -> dict[str, str]:  # pragma: no cover
        return {"order_id": order_id}

    assert route_template(app, "/orders/abc-123") == "/orders/{order_id}"
    assert route_template(app, "/nonexistent") == "UNMATCHED"


def test_no_high_cardinality_labels_after_many_requests() -> None:
    """Raw paths must collapse onto route templates before hitting metrics."""
    from fastapi import FastAPI

    from traceforge.core.middleware import route_template

    app = FastAPI()

    @app.get("/orders/{order_id}")
    async def order(order_id: str) -> dict[str, str]:  # pragma: no cover
        return {"order_id": order_id}

    state = MetricsState("test-svc", registry=CollectorRegistry())
    for i in range(500):
        # Exactly what MetricsMiddleware does: resolve template first.
        template = route_template(app, f"/orders/{i}")
        state.observe_request("GET", template, 200, 0.001)
    assert len(counter_snapshot(state.requests_total)) == 1


def test_redact_headers() -> None:
    redacted = redact_headers(
        {"Authorization": "Bearer secret", "Cookie": "a=b", "X-Api-Key": "k", "Accept": "*/*"}
    )
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["X-Api-Key"] == "[REDACTED]"
    assert "Cookie" not in redacted
    assert redacted["Accept"] == "*/*"
