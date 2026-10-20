"""HTTP middleware that produces request metrics with bounded-cardinality labels.

Cardinality discipline (docs/TELEMETRY_DESIGN.md): labels may only contain
``service``, ``method``, ``route`` (the *template*, e.g. ``/orders/{id}``)
and ``status``.  Trace IDs, raw paths with IDs and exception messages are
never used as label values.
"""

from __future__ import annotations

import logging
import time

from prometheus_client import (
    CollectorRegistry,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client import (
    Counter as PromCounter,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

LATENCY_THRESHOLD_S_DEFAULT = 1.0


class MetricsState:
    """Holder for the metric family of one service."""

    def __init__(self, service_name: str, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        prefix = "tf"
        labels = ["service", "method", "route", "status"]
        self.requests_total = PromCounter(
            f"{prefix}_http_requests_total",
            "Total HTTP requests handled.",
            labels,
            registry=self.registry,
        )
        self.request_errors_total = PromCounter(
            f"{prefix}_http_request_errors_total",
            "HTTP requests answered with status >= 500.",
            labels,
            registry=self.registry,
        )
        self.request_seconds = Histogram(
            f"{prefix}_http_request_duration_seconds",
            "HTTP request duration in seconds.",
            labels,
            buckets=BUCKETS,
            registry=self.registry,
        )
        self.downstream_failures_total = PromCounter(
            f"{prefix}_downstream_failures_total",
            "Failures while calling a downstream dependency.",
            ["service", "downstream", "kind"],
            registry=self.registry,
        )
        self.otel_export_failures_total = PromCounter(
            f"{prefix}_otel_export_failures_total",
            "Failed OpenTelemetry export rounds.",
            ["service", "signal"],
            registry=self.registry,
        )
        self.unhandled_exceptions_total = PromCounter(
            f"{prefix}_unhandled_exceptions_total",
            "Requests that ended in an unhandled exception.",
            ["service", "route"],
            registry=self.registry,
        )
        self.latency_threshold_breaches_total = PromCounter(
            f"{prefix}_latency_threshold_breaches_total",
            "Requests whose observed latency crossed the configured threshold.",
            ["service", "route"],
            registry=self.registry,
        )
        self.inflight_requests = Gauge(
            f"{prefix}_http_inflight_requests",
            "Requests currently being handled.",
            ["service"],
            registry=self.registry,
        )
        self.service_up = Gauge(
            f"{prefix}_service_up",
            "1 when the service answered its own readiness probe recently.",
            ["service"],
            registry=self.registry,
        )
        self.latency_threshold_seconds = Gauge(
            f"{prefix}_latency_threshold_seconds",
            "Configured latency threshold used by the breach detector.",
            ["service"],
            registry=self.registry,
        )
        self.service_name = service_name
        self.latency_threshold_s = LATENCY_THRESHOLD_S_DEFAULT

    # -- helpers used by the middleware ------------------------------------
    def observe_request(
        self, method: str, route: str, status: int, duration_s: float
    ) -> None:
        labels = [self.service_name, method, route, str(status)]
        self.requests_total.labels(*labels).inc()
        self.request_seconds.labels(*labels).observe(duration_s)
        if status >= 500:
            self.request_errors_total.labels(*labels).inc()
        if duration_s >= self.latency_threshold_s:
            self.latency_threshold_breaches_total.labels(
                *[self.service_name, route]
            ).inc()

    def observe_downstream_failure(self, downstream: str, kind: str) -> None:
        self.downstream_failures_total.labels(
            *[self.service_name, downstream, kind]
        ).inc()

    def render_prometheus(self) -> bytes:
        return generate_latest(self.registry)


def route_template(app: ASGIApp, scope_path: str, method: str = "GET") -> str:
    """Resolve the route *template* for a raw request path."""
    routes = getattr(app, "routes", [])
    for route in routes:
        try:
            match, _child_scope = route.matches(
                {"type": "http", "path": scope_path, "method": method}
            )
        except (TypeError, ValueError, KeyError):
            continue
        if match == Match.FULL:
            return getattr(route, "path", scope_path)
    return "UNMATCHED"


class MetricsMiddleware(BaseHTTPMiddleware):
    """Prometheus request metrics with template-based route labels."""

    def __init__(self, app: ASGIApp, state: MetricsState) -> None:
        super().__init__(app)
        self.state = state

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        template = route_template(request.app, request.url.path, request.method)
        # Exclude the metrics + health endpoints themselves from metrics to
        # avoid scrape noise dominating the request volume.
        if template in {"/metrics", "/healthz", "/readyz"}:
            return await call_next(request)

        self.state.inflight_requests.labels(*[self.state.service_name]).inc()
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            self.state.inflight_requests.labels(*[self.state.service_name]).dec()
            self.state.observe_request(
                request.method, template, status, duration
            )


class RequestIDNotFound(Exception):
    """Raised by helpers when a request lacks the expected attribute."""


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Strip sensitive headers before any telemetry or log emission."""
    dropped = {"cookie", "set-cookie"}
    redact = {"authorization", "x-api-key"}
    return {
        k: ("[REDACTED]" if k.lower() in redact else v)
        for k, v in headers.items()
        if k.lower() not in dropped
    }


def counter_snapshot(counter: PromCounter) -> dict[tuple[str, ...], float]:
    """Return the current labeled values of a ``prometheus_client`` counter.

    Only used by tests and health diagnostics; never served as telemetry.
    """
    values: dict[tuple[str, ...], float] = {}
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_created"):
                continue
            values[tuple(sample.labels.values())] = sample.value
    return values
