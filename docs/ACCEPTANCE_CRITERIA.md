# Acceptance Criteria

| # | Criterion | How verified | Status |
|---|---|---|---|
| 1 | Three separately identifiable FastAPI services (gateway, order, inventory) communicating over real HTTP | `tests/integration/test_trace_propagation.py` starts all three as uvicorn subprocesses | ✅ verified |
| 2 | One trace id per distributed request; parent-child spans match real call flow | `test_full_trace_propagation_across_three_processes` asserts shared trace id + parent ids decoded from real OTLP exports | ✅ verified |
| 3 | W3C `traceparent` honored from external clients | `test_w3c_traceparent_header_manually_injected_is_honoured` | ✅ verified |
| 4 | OTLP Collector receives telemetry and forwards to Tempo | `collector/config.yaml` written and schema-validated by `scripts/validate_configs.py` | ⚠️ config verified; runtime unverified (no Docker in build environment) |
| 5 | Prometheus scrapes app metrics | `prometheus/prometheus.yml` targets written; schema-validated | ⚠️ config verified; scraping unverified (no Docker) |
| 6 | Alert rules for error rate, latency, availability, export failures | `prometheus/rules/alerts.yml`; presence checked by validator | ⚠️ rules written; firing behavior unverified (no Docker) |
| 7 | Grafana provisioning + dashboards | `grafana/provisioning/` + `grafana/dashboards/overview.json` | ⚠️ JSON written; rendering unverified (no Docker) |
| 8 | Trace-correlated structured logs; explicit `null` when no trace | `tests/unit/test_logging_correlation.py` (real trace id asserted from live span) | ✅ verified |
| 9 | Latency threshold detection, deterministic | `tests/unit/test_detector.py`, `test_threshold_scenario_crosses_detector` (duration from real span) | ✅ verified |
| 10 | Bounded metric cardinality (no trace ids / raw paths as labels) | `test_no_high_cardinality_labels_after_many_requests` (500 raw paths → 1 label set) | ✅ verified |
| 11 | Sensitive data excluded from telemetry/logs | `test_redact_headers`, `test_sensitive_values_not_in_log_schema` | ✅ verified |
| 12 | Graceful behavior when telemetry exporter unavailable | `test_metrics_survive_collector_outage`, `ResilientSpanExporter` + failure counter | ✅ verified (service side; Collector side unverified) |
| 13 | Fault injection disabled in production config | `test_fault_injection_forbidden_in_production`, `test_production_defaults_disable_fault_injection` | ✅ verified |
| 14 | Health + readiness endpoints | `test_health_and_readiness` + integration `test_health_endpoints_answer` (real processes) | ✅ verified |
| 15 | Docker Compose stack starts end-to-end | Requires Docker | ❌ not executable here — not claimed |
| 16 | Release ZIP validated | `unzip -t` + content listing | ✅ verified |
