"""Typed configuration for TraceForge services.

Every knob is environment-driven (12-factor style) with safe development
defaults.  ``validate`` enforces the invariants documented in
docs/TELEMETRY_DESIGN.md so that a misconfigured deployment fails fast at
startup instead of silently dropping telemetry.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ScenarioName = Literal["ok", "slow", "error", "exception", "threshold", "unavailable", "noisy"]


class ConfigError(ValueError):
    """Raised when configuration values violate documented invariants."""


class ServiceConfig(BaseSettings):
    """Base configuration shared by every TraceForge service."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    # --- service identity -------------------------------------------------
    service_name: str = Field(default="traceforge-unknown", alias="OTEL_SERVICE_NAME")
    environment: Literal["development", "production"] = Field(
        default="development", alias="TF_ENVIRONMENT"
    )
    host: str = Field(default="0.0.0.0", alias="TF_HOST")
    port: int = Field(default=8000, alias="TF_PORT")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", alias="TF_LOG_LEVEL"
    )

    # --- OpenTelemetry trace export ---------------------------------------
    otel_exporter_protocol: Literal["grpc", "http/protobuf"] = Field(
        default="http/protobuf", alias="TF_OTEL_EXPORTER_PROTOCOL"
    )
    otel_exporter_endpoint: str = Field(
        default="http://otel-collector:4318/v1/traces",
        alias="TF_OTEL_EXPORTER_ENDPOINT",
    )
    otel_export_timeout_millis: int = Field(
        default=5000, alias="TF_OTEL_EXPORT_TIMEOUT_MS"
    )
    otel_schedule_delay_millis: int = Field(default=500, alias="TF_OTEL_SCHEDULE_DELAY_MS")
    otel_export_enabled: bool = Field(default=True, alias="TF_OTEL_EXPORT_ENABLED")

    # --- fault injection (development only) --------------------------------
    # None means "follow the environment default": enabled in development,
    # disabled in production.  An explicit value always wins.
    fault_injection_enabled: bool | None = Field(
        default=None, alias="TF_FAULT_INJECTION_ENABLED"
    )
    slow_delay_ms: int = Field(default=1500, alias="TF_SLOW_DELAY_MS")
    latency_threshold_ms: int = Field(default=1000, alias="TF_LATENCY_THRESHOLD_MS")
    error_rate: float = Field(default=0.0, alias="TF_ERROR_RATE")
    inventory_timeout_s: float = Field(default=2.0, alias="TF_INVENTORY_TIMEOUT_S")
    noisy_heartbeat_interval_s: float = Field(
        default=0.0, alias="TF_NOISY_HEARTBEAT_INTERVAL_S"
    )

    # --- downstream peers (host:port, no scheme; http is added by callers) --
    inventory_url: str = Field(
        default="http://inventory-service:8000", alias="TF_INVENTORY_URL"
    )
    order_url: str = Field(default="http://order-service:8000", alias="TF_ORDER_URL")

    # --- observability self-exposure ----------------------------------------
    metrics_path: str = Field(default="/metrics", alias="TF_METRICS_PATH")

    def effective_fault_injection(self) -> bool:
        if self.fault_injection_enabled is None:
            return self.environment == "development"
        return self.fault_injection_enabled

    def validate_config(self) -> None:
        """Fail fast on configuration that violates documented invariants."""
        errors: list[str] = []
        if self.slow_delay_ms < 0:
            errors.append("TF_SLOW_DELAY_MS must be >= 0")
        if self.latency_threshold_ms <= 0:
            errors.append("TF_LATENCY_THRESHOLD_MS must be > 0")
        if not 0.0 <= self.error_rate <= 1.0:
            errors.append("TF_ERROR_RATE must be within [0.0, 1.0]")
        if self.inventory_timeout_s <= 0:
            errors.append("TF_INVENTORY_TIMEOUT_S must be > 0")
        if not self.otel_exporter_endpoint.startswith(("http://", "https://")):
            errors.append("TF_OTEL_EXPORTER_ENDPOINT must be an http(s) URL")
        if self.environment == "production" and self.effective_fault_injection():
            # Hard invariant: fault injection must never be reachable in a
            # production configuration (docs/SECURITY.md).
            errors.append(
                "TF_FAULT_INJECTION_ENABLED must be false when TF_ENVIRONMENT=production"
            )
        if errors:
            raise ConfigError("; ".join(errors))

    def is_fault_injection_active(self) -> bool:
        """Fault injection endpoints are only active in development builds."""
        return self.environment == "development" and self.effective_fault_injection()


def load_config() -> ServiceConfig:
    """Load configuration from the environment and validate it."""
    config = ServiceConfig()  # type: ignore[call-arg]
    config.validate_config()
    return config


def ensure_free_port(host: str, port: int) -> int:  # pragma: no cover - test helper
    """Return ``port`` if bindable, otherwise an ephemeral free port (tests/dev)."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return 0
    return port


def env_bool(name: str, default: bool) -> bool:  # pragma: no cover - trivial
    """Parse a boolean environment variable the way docker-compose users expect."""
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}
