"""Unit tests for configuration loading and validation."""

from __future__ import annotations

import pytest

from traceforge.core.config import ConfigError, load_config


def test_development_defaults_load(dev_env: dict[str, str]) -> None:
    config = load_config()
    assert config.service_name == "test-service"
    assert config.environment == "development"
    assert config.otel_exporter_protocol == "http/protobuf"
    assert config.is_fault_injection_active() is True


def test_latency_threshold_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_LATENCY_THRESHOLD_MS", "0")
    with pytest.raises(ConfigError, match="TF_LATENCY_THRESHOLD_MS"):
        load_config()


def test_error_rate_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_ERROR_RATE", "1.5")
    with pytest.raises(ConfigError, match="TF_ERROR_RATE"):
        load_config()


def test_fault_injection_forbidden_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_ENVIRONMENT", "production")
    monkeypatch.setenv("TF_FAULT_INJECTION_ENABLED", "true")
    with pytest.raises(ConfigError, match="TF_FAULT_INJECTION_ENABLED"):
        load_config()


def test_production_defaults_disable_fault_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_ENVIRONMENT", "production")
    config = load_config()
    assert config.is_fault_injection_active() is False


def test_invalid_exporter_endpoint_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_OTEL_EXPORTER_ENDPOINT", "not-a-url")
    with pytest.raises(ConfigError, match="TF_OTEL_EXPORTER_ENDPOINT"):
        load_config()


def test_environment_aliases_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_OTEL_EXPORTER_PROTOCOL", "grpc")
    monkeypatch.setenv("TF_SLOW_DELAY_MS", "2500")
    config = load_config()
    assert config.otel_exporter_protocol == "grpc"
    assert config.slow_delay_ms == 2500
