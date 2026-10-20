"""Deterministic demo scenarios shared by the TraceForge services.

Each scenario is a deliberate, named behaviour used to generate specific
telemetry shapes (traces, metrics, logs).  Scenarios are only reachable via
the fault-injection API, which is disabled unless
``TF_ENVIRONMENT=development`` and ``TF_FAULT_INJECTION_ENABLED=true``.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

Scenario = Literal[
    "ok",
    "slow",
    "error",
    "exception",
    "threshold",
    "unavailable",
    "noisy",
]

KNOWN_SCENARIOS: tuple[str, ...] = (
    "ok",
    "slow",
    "error",
    "exception",
    "threshold",
    "unavailable",
    "noisy",
)


class ScenarioError(ValueError):
    """Raised when an unknown scenario name is requested."""


@dataclass
class ScenarioResult:
    """Outcome of running a scenario inside the inventory service."""

    scenario: Scenario
    detail: str
    latency_ms: float
    status: Literal["ok", "error"]


@dataclass
class ScenarioRunner:
    """Executes deterministic scenarios with an injectable RNG.

    ``random`` is injectable so tests are fully deterministic.
    """

    slow_delay_ms: int = 1500
    latency_threshold_ms: int = 1000
    error_rate: float = 0.0
    rng: random.Random = field(default_factory=random.Random)

    def run(self, scenario: Scenario) -> ScenarioResult:
        if scenario not in KNOWN_SCENARIOS:  # pragma: no cover - guarded by API layer
            raise ScenarioError(f"unknown scenario: {scenario!r}")

        if scenario == "ok":
            return ScenarioResult("ok", "inventory lookup succeeded", 1.0, "ok")

        if scenario == "slow":
            return self._delayed("slow", self.slow_delay_ms)

        if scenario == "threshold":
            # Crosses the documented latency threshold by a fixed margin so
            # the threshold detector has a deterministic input.
            delay = self.latency_threshold_ms + 250
            return self._delayed("threshold", delay)

        if scenario == "error":
            raise InventoryUnavailableError("inventory returned HTTP 503 (injected)")

        if scenario == "exception":
            raise InventoryFailure("simulated inventory cache failure (injected)")

        if scenario == "unavailable":
            raise InventoryConnectionError("connection to inventory refused (injected)")

        if scenario == "noisy":
            for _ in range(3):
                logger.info(
                    "noisy heartbeat: generating telemetry volume for alert testing"
                )
            return ScenarioResult("noisy", "3 heartbeat log lines emitted", 1.0, "ok")

        raise ScenarioError(f"unhandled scenario: {scenario!r}")  # pragma: no cover

    def _delayed(self, name: Scenario, delay_ms: int) -> ScenarioResult:
        import time

        start = time.perf_counter()
        time.sleep(delay_ms / 1000.0)
        elapsed = (time.perf_counter() - start) * 1000.0
        return ScenarioResult(name, f"slept {delay_ms} ms", elapsed, "ok")

    def maybe_random_error(self) -> bool:
        """Return True when the configured random error rate fires."""
        return self.error_rate > 0 and self.rng.random() < self.error_rate


class InventoryError(RuntimeError):
    """Base class for inventory failures used in demo scenarios."""


class InventoryUnavailableError(InventoryError):
    """Downstream responded with an HTTP error status."""


class InventoryFailure(InventoryError):
    """Downstream raised an unexpected exception."""


class InventoryConnectionError(InventoryError):
    """Downstream could not be reached at all (connection refused / timeout)."""
