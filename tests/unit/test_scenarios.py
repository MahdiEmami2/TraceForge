"""Unit tests for the deterministic scenario runner."""

from __future__ import annotations

import random

import pytest

from traceforge.core.scenarios import (
    InventoryConnectionError,
    InventoryFailure,
    InventoryUnavailableError,
    ScenarioRunner,
)


def _runner(**kwargs: object) -> ScenarioRunner:
    kwargs.setdefault("rng", random.Random(7))
    return ScenarioRunner(**kwargs)  # type: ignore[arg-type]


def test_ok_is_fast_and_successful() -> None:
    result = _runner().run("ok")
    assert result.status == "ok"
    assert result.latency_ms < 50


def test_slow_sleeps_configured_delay() -> None:
    result = _runner(slow_delay_ms=150).run("slow")
    assert result.status == "ok"
    assert result.latency_ms >= 140


def test_threshold_crosses_documented_margin() -> None:
    runner = _runner(latency_threshold_ms=200)
    result = runner.run("threshold")
    assert result.latency_ms >= 200 + 200  # 250ms sleep + scheduling slack
    assert result.scenario == "threshold"


def test_error_raises_http_style_failure() -> None:
    with pytest.raises(InventoryUnavailableError):
        _runner().run("error")


def test_exception_raises_internal_failure() -> None:
    with pytest.raises(InventoryFailure):
        _runner().run("exception")


def test_unavailable_raises_connection_failure() -> None:
    with pytest.raises(InventoryConnectionError):
        _runner().run("unavailable")


def test_noisy_produces_logs_and_success() -> None:
    result = _runner().run("noisy")
    assert result.status == "ok"


def test_unknown_scenario_rejected() -> None:
    with pytest.raises(Exception):
        _runner().run("nonsense")  # type: ignore[arg-type]


def test_random_error_rate_is_deterministic_with_seed() -> None:
    runner = _runner(error_rate=1.0)
    assert runner.maybe_random_error() is True
    zero = _runner(error_rate=0.0)
    assert zero.maybe_random_error() is False
