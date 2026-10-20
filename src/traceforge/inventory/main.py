"""Inventory Service - downstream dependency with deterministic fault scenarios."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from ..core.app_factory import create_app
from ..core.config import ScenarioName, load_config
from ..core.scenarios import InventoryError, ScenarioRunner

logger = logging.getLogger("traceforge.inventory")
def _tracer():
    return trace.get_tracer("traceforge.inventory")


_CATALOG: dict[str, dict[str, Any]] = {
    "SKU-1": {"name": "Keyboard", "available": 42},
    "SKU-2": {"name": "Mouse", "available": 7},
    "SKU-3": {"name": "Monitor", "available": 0},
}


class ScenarioRequest(BaseModel):
    scenario: ScenarioName = "ok"
    sku: str = Field(default="SKU-1", min_length=1, max_length=64)


def build_router(runner: ScenarioRunner | None = None) -> APIRouter:
    router = APIRouter()

    @router.get("/inventory", tags=["business"])
    async def inventory(
        request: Request, sku: str = Query(min_length=1, max_length=64)
    ) -> Any:
        """Returns stock for a SKU; honours the service-level scenario override."""
        config = request.app.state.config
        scenario: str = request.app.state.scenario_override or "ok"
        with _tracer().start_as_current_span("inventory.lookup") as span:
            span.set_attribute("inventory.sku", sku)
            span.set_attribute("inventory.scenario", scenario)

            if scenario != "ok":
                try:
                    ScenarioRunner(
                        slow_delay_ms=config.slow_delay_ms,
                        latency_threshold_ms=config.latency_threshold_ms,
                    ).run(scenario)  # type: ignore[arg-type]
                except InventoryError as exc:
                    span.set_status(Status(StatusCode.ERROR, str(type(exc).__name__)))
                    span.record_exception(exc)
                    logger.error(
                        "inventory scenario %s failed: %s", scenario, type(exc).__name__
                    )
                    if isinstance(exc, InventoryError) and "HTTP 503" in str(exc):
                        raise HTTPException(status_code=503, detail="inventory degraded") from exc
                    raise HTTPException(status_code=500, detail="inventory failure") from exc

            item = _CATALOG.get(sku)
            if item is None:
                raise HTTPException(status_code=404, detail="unknown sku")
            return {"sku": sku, **item}

    @router.post("/inventory/scenario", tags=["fault-injection"])
    async def set_scenario(payload: ScenarioRequest, request: Request) -> dict[str, str | bool]:
        """Development-only: set a sticky scenario for subsequent inventory calls."""
        config = request.app.state.config
        if not config.is_fault_injection_active():
            raise HTTPException(status_code=403, detail="fault injection disabled")
        request.app.state.scenario_override = payload.scenario
        logger.warning("scenario override set to %s", payload.scenario)
        return {"scenario": payload.scenario, "active": True}

    @router.delete("/inventory/scenario", tags=["fault-injection"])
    async def clear_scenario(request: Request) -> dict[str, str | bool]:
        config = request.app.state.config
        if not config.is_fault_injection_active():
            raise HTTPException(status_code=403, detail="fault injection disabled")
        request.app.state.scenario_override = None
        return {"scenario": "ok", "active": False}

    return router


def create_inventory_app() -> Any:
    """Application factory - used by uvicorn via ``--factory`` and by tests."""
    config = load_config()
    app = create_app(
        "inventory-service",
        config=config,
        extra_routers={"": build_router()},
    )
    app.state.scenario_override = None
    return app
