"""Order Service - handles the simulated business operation and calls Inventory."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from ..core.app_factory import create_app
from ..core.config import load_config

logger = logging.getLogger("traceforge.orders")
def _tracer():
    return trace.get_tracer("traceforge.orders")



class OrderRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=1000, default=1)


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/orders", tags=["business"])
    async def create_order(payload: OrderRequest, request: Request) -> Any:
        config = request.app.state.config
        with _tracer().start_as_current_span("orders.create") as span:
            span.set_attribute("order.sku", payload.sku)
            span.set_attribute("order.quantity", payload.quantity)
            order_id = f"ord-{uuid.uuid4().hex[:12]}"
            span.set_attribute("order.id", order_id)
            logger.info("creating order sku=%s qty=%s", payload.sku, payload.quantity)

            try:
                async with httpx.AsyncClient(timeout=config.inventory_timeout_s) as client:
                    inv_resp = await client.get(
                        f"{config.inventory_url}/inventory",
                        params={"sku": payload.sku},
                    )
            except httpx.RequestError as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, "inventory unreachable"))
                request.app.state.metrics_state.observe_downstream_failure(
                    "inventory-service", type(exc).__name__
                )
                logger.error("inventory unreachable: %s", type(exc).__name__)
                raise HTTPException(status_code=503, detail="inventory unavailable") from exc

            if inv_resp.status_code >= 400:
                span.set_attribute("inventory.status", inv_resp.status_code)
                request.app.state.metrics_state.observe_downstream_failure(
                    "inventory-service", f"http-{inv_resp.status_code}"
                )
                logger.warning("inventory returned http %s", inv_resp.status_code)
                raise HTTPException(status_code=502, detail="inventory error")

            span.set_status(StatusCode.OK)
            return {
                "order_id": order_id,
                "status": "confirmed",
                "inventory": inv_resp.json(),
            }

    @router.get("/inventory", tags=["business"])
    async def lookup_inventory(sku: str, request: Request) -> Any:
        """Proxy hop so traces contain gateway -> order -> inventory depth."""
        config = request.app.state.config
        try:
            async with httpx.AsyncClient(timeout=config.inventory_timeout_s) as client:
                resp = await client.get(
                    f"{config.inventory_url}/inventory", params={"sku": sku}
                )
        except httpx.RequestError as exc:
            request.app.state.metrics_state.observe_downstream_failure(
                "inventory-service", type(exc).__name__
            )
            raise HTTPException(status_code=503, detail="inventory unavailable") from exc
        return JSONResponse(status_code=resp.status_code, content=resp.json())

    return router


def create_orders_app() -> Any:
    """Application factory - used by uvicorn via ``--factory``."""
    config = load_config()
    return create_app("order-service", config=config, extra_routers={"": build_router()})
