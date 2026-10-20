"""API Gateway - entry point for every client request."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel, Field

from ..core.app_factory import create_app
from ..core.config import load_config

logger = logging.getLogger("traceforge.gateway")
def _tracer():
    return trace.get_tracer("traceforge.gateway")



class CheckoutRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=1000, default=1)


class GatewayResult(BaseModel):
    order_id: str
    status: str
    inventory: dict[str, Any] | None = None
    error: str | None = None


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/checkout", response_model=GatewayResult, tags=["business"])
    async def checkout(payload: CheckoutRequest, request: Request) -> GatewayResult:
        """Orchestrates a checkout: calls the order service, which calls inventory."""
        config = request.app.state.config
        with _tracer().start_as_current_span("gateway.checkout") as span:
            span.set_attribute("order.sku", payload.sku)
            span.set_attribute("order.quantity", payload.quantity)
            try:
                async with httpx.AsyncClient(timeout=config.inventory_timeout_s) as client:
                    resp = await client.post(
                        f"{config.order_url}/orders",
                        json=payload.model_dump(),
                    )
            except httpx.RequestError as exc:
                span.record_exception(exc)
                span.set_attribute("gateway.failure", "order-unreachable")
                request.app.state.metrics_state.observe_downstream_failure(
                    "order-service", type(exc).__name__
                )
                raise HTTPException(status_code=502, detail="order service unreachable") from exc

            if resp.status_code >= 400:
                request.app.state.metrics_state.observe_downstream_failure(
                    "order-service", f"http-{resp.status_code}"
                )
                span.set_attribute("gateway.failure", f"order-http-{resp.status_code}")
                raise HTTPException(status_code=resp.status_code, detail="order failed")

            data = resp.json()
            span.set_attribute("order.id", str(data.get("order_id", "")))
            return GatewayResult(
                order_id=str(data.get("order_id", "")),
                status=str(data.get("status", "unknown")),
                inventory=data.get("inventory"),
            )

    @router.get("/api/inventory-lookup", tags=["business"])
    async def inventory_lookup(sku: str, request: Request) -> Any:
        """Direct inventory lookup through the order service hop."""
        config = request.app.state.config
        try:
            async with httpx.AsyncClient(timeout=config.inventory_timeout_s) as client:
                resp = await client.get(
                    f"{config.order_url}/inventory",
                    params={"sku": sku},
                )
        except httpx.RequestError as exc:
            request.app.state.metrics_state.observe_downstream_failure(
                "order-service", type(exc).__name__
            )
            raise HTTPException(status_code=502, detail="order service unreachable") from exc
        return JSONResponse(status_code=resp.status_code, content=resp.json())

    return router


def create_gateway_app() -> Any:
    """Application factory - used by uvicorn via ``--factory``."""
    config = load_config()
    return create_app("gateway", config=config, extra_routers={"": build_router()})
