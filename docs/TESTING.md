# Testing

## Commands (exact, from the build session; Python 3.12.3, venv `/home/user/tfvenv`)

```
$ cd /home/user/traceforge && /home/user/tfvenv/bin/python -m pytest tests/integration tests/unit -q
47 passed, 1 warning in 10.58s

$ /home/user/tfvenv/bin/ruff check src tests
(Specifies only a pre-existing B017 noqa case; clean after fixes — 0 errors)

$ /home/user/tfvenv/bin/mypy src
Success: no issues found in 16 source files

$ /home/user/tfvenv/bin/python scripts/validate_configs.py
OK: all configuration files valid (0 problems)
```

## What is covered where

| Area | Tests |
|---|---|
| Success/error behavior, health/readiness | `tests/unit/test_app_instrumentation.py` (in-process ASGI), integration health test |
| FastAPI route instrumentation | unit span tests with `InMemorySpanExporter` |
| Trace id propagation across services | `tests/integration/test_trace_propagation.py::test_full_trace_propagation_across_three_processes` (real processes + real OTLP) |
| Parent-child span relationships | same integration test (parents decoded from exported protobuf) |
| W3C traceparent from external client | `test_w3c_traceparent_header_manually_injected_is_honoured` |
| Exception recording | `test_scenario_exception_recorded_on_span` |
| Downstream timeout/failure behavior | scenario tests (error/unavailable), unit scenario runner |
| Metric creation + label correctness | `tests/unit/test_metrics.py` |
| Latency threshold detection | `tests/unit/test_detector.py`, `test_threshold_scenario_crosses_detector` |
| Configuration validation | `tests/unit/test_config.py` |
| Sensitive data exclusion | `test_redact_headers`, `test_sensitive_values_not_in_log_schema` |
| Graceful exporter outage | `test_metrics_survive_collector_outage` + `ResilientSpanExporter` counter |

## Not executed (environment limitation)

Docker is unavailable in this sandbox, so the following were **not** run and are not claimed: `docker compose up` end-to-end, Tempo ingestion, Prometheus scraping, Grafana rendering, `otelcol validate`/`promtool` binary checks. Equivalent config schema checks run via `scripts/validate_configs.py`. Do not mistake the green integration tests for a validated Docker stack — they validate the *applications and the OTLP path*, not the container configuration.
