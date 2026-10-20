"""Shared pytest fixtures for TraceForge tests."""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

# Must run before any traceforge module import so that module-level app
# factories never build real OTLP exporters (no network in unit tests).
os.environ.setdefault("TF_OTEL_EXPORT_ENABLED", "false")

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import pytest  # noqa: E402


@pytest.fixture()
def deterministic_rng() -> random.Random:
    return random.Random(1234)


@pytest.fixture()
def dev_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Baseline development environment for config loading."""
    env = {
        "TF_ENVIRONMENT": "development",
        "OTEL_SERVICE_NAME": "test-service",
        "TF_OTEL_EXPORT_ENABLED": "false",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env
