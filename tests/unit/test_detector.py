"""Unit tests for the static latency-threshold detector."""

from __future__ import annotations

import pytest

from traceforge.core.detector import ThresholdDetector


def test_normal_request_below_threshold() -> None:
    verdict = ThresholdDetector(1000).classify(120.0)
    assert verdict.classification == "normal"
    assert verdict.is_breach is False


def test_slow_request_breaches() -> None:
    verdict = ThresholdDetector(1000).classify(1500.0)
    assert verdict.classification == "slow"
    assert verdict.is_breach is True


def test_exact_threshold_counts_as_breach() -> None:
    assert ThresholdDetector(1000).classify(1000.0).is_breach is True


def test_threshold_must_be_positive() -> None:
    with pytest.raises(ValueError):
        ThresholdDetector(0)


def test_detector_deterministic() -> None:
    detector = ThresholdDetector(500)
    assert detector.classify(499.9).is_breach is False
    assert detector.classify(499.9).is_breach is False
    assert detector.classify(501.0).is_breach is True
