"""FastAPI application factory shared by all three TraceForge services.

Wires, in one place: tracing, metrics middleware, structured logging,
health/readiness, the demo business routes and the development-only fault
injection API.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from pydantic import BaseModel

from .config import ServiceConfig, load_config
from .logging_setup import configure_logging
from .middleware import MetricsMiddleware, MetricsState
from .telemetry import (
    configure_metrics,
    configure_tracing,
    export_failures,
)

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    environment: str
    otel_export_failures: int


class ReadyResponse(BaseModel):
    ready: bool
    service: str
    reason: str | None = None


def create_app(
    service_name: str,
    config: ServiceConfig | None = None,
    extra_routers: dict[str, APIRouter] | None = None,
    metrics_state: MetricsState | None = None,
    lifespan: Any = None,
    tracer_provider: Any = None,
) -> FastAPI:
    """Build a fully instrumented FastAPI app for one TraceForge service."""
    config = config or load_config()
    configure_logging(config.service_name, config.log_level)

    state = metrics_state or MetricsState(service_name)
    state.latency_threshold_s = config.latency_threshold_ms / 1000.0
    state.latency_threshold_seconds.labels(*[service_name]).set(
        config.latency_threshold_ms / 1000.0
    )

    resource = __import__(
        "traceforge.core.telemetry", fromlist=["build_resource"]
    ).build_resource(service_name, config.environment)
    if tracer_provider is None:
        configure_tracing(
            resource,
            config.otel_exporter_protocol,
            config.otel_exporter_endpoint,
            config.otel_export_timeout_millis,
            config.otel_schedule_delay_millis,
            config.otel_export_enabled,
        )
    configure_metrics(resource)

    app = FastAPI(
        title=f"TraceForge :: {service_name}",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(MetricsMiddleware, state=state)
    app.state.metrics_state = state
    app.state.config = config

    core = APIRouter()

    @core.get("/healthz", response_model=HealthResponse, tags=["health"])
    async def healthz() -> HealthResponse:
        return HealthResponse(
            service=service_name,
            environment=config.environment,
            otel_export_failures=export_failures(),
        )

    @core.get("/readyz", response_model=ReadyResponse, tags=["health"])
    async def readyz() -> ReadyResponse:
        return ReadyResponse(ready=True, service=service_name)

    @core.get(config.metrics_path, tags=["health"], include_in_schema=False)
    async def metrics() -> Response:
        return Response(
            content=state.render_prometheus(), media_type="text/plain; version=0.0.4"
        )

    @core.get("/", tags=["health"])
    async def index() -> dict[str, str]:
        return {"service": service_name, "docs": "/docs"}

    app.include_router(core)
    for prefix, router in (extra_routers or {}).items():
        app.include_router(router, prefix=prefix)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    # Shared-noise guard: unhandled exceptions are logged with stack traces
    # and re-raised so the ASGI server returns a safe 500 (no internals leak).
    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled exception: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider or trace.get_tracer_provider(),
        excluded_urls="healthz,readyz",
    )
    # Outbound httpx calls MUST be instrumented: without it the traceparent
    # header is never injected and downstream services start unrelated traces
    # (caught by tests/integration/test_trace_propagation.py).
    HTTPXClientInstrumentor().instrument(tracer_provider=tracer_provider or trace.get_tracer_provider())
    return app
