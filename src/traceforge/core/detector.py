"""Transparent latency-threshold detection.

Detector contract (docs/TELEMETRY_DESIGN.md):
- The threshold is a *configurable static* value (``TF_LATENCY_THRESHOLD_MS``).
- A request whose observed duration >= threshold breaches exactly once.
- Breaches are exported both as a Prometheus counter (see middleware) and as
  a span event so the slow request is visible in the trace backend too.

The detector is intentionally simple and deterministic.  It is *not* a
baseline/ML anomaly detector; the distinction is documented in the README.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DetectionVerdict:
    is_breach: bool
    observed_ms: float
    threshold_ms: int
    classification: Literal["normal", "slow"]


class ThresholdDetector:
    """Classify a single request duration against a static threshold."""

    def __init__(self, threshold_ms: int) -> None:
        if threshold_ms <= 0:
            raise ValueError("threshold_ms must be > 0")
        self.threshold_ms = threshold_ms

    def classify(self, duration_ms: float) -> DetectionVerdict:
        is_breach = duration_ms >= self.threshold_ms
        return DetectionVerdict(
            is_breach=is_breach,
            observed_ms=duration_ms,
            threshold_ms=self.threshold_ms,
            classification="slow" if is_breach else "normal",
        )
