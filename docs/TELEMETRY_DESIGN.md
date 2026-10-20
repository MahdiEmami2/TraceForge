# Telemetry Design

## Traces

- SDK: `opentelemetry-sdk==1.39.1` + `opentelemetry-instrumentation-fastapi==0.60b1` / `-httpx==0.60b1` (same release train).
- Resource attributes on every signal: `service.name`, `service.namespace=traceforge`, `deployment.environment`.
- Export: OTLP/HTTP to `http://otel-collector:4318/v1/traces` via `BatchSpanProcessor` (500 ms schedule delay).
- `ResilientSpanExporter` wraps the exporter: Collector outages are non-fatal, counted in `tf_otel_export_failures_total`, and logged once.
- Health endpoints (`/healthz`, `/readyz`) are excluded from tracing and metrics.
- Manual spans: `gateway.checkout`, `orders.create`, `inventory.lookup` with bounded attributes (`order.sku`, `order.quantity`, `inventory.scenario` — no raw user payload).

## Metrics (Prometheus, `prometheus-client`, prefix `tf_`)

| Metric | Type | Labels (bounded) | Interpretation |
|---|---|---|---|
| `tf_http_requests_total` | counter | service, method, route, status | request volume |
| `tf_http_request_errors_total` | counter | service, method, route, status | 5xx only |
| `tf_http_request_duration_seconds` | histogram | service, method, route, status | latency distribution |
| `tf_downstream_failures_total` | counter | service, downstream, kind | dependency failures |
| `tf_otel_export_failures_total` | counter | service, signal | telemetry pipeline health |
| `tf_unhandled_exceptions_total` | counter | service, route | escaped errors |
| `tf_latency_threshold_breaches_total` | counter | service, route | slow-request detector output |
| `tf_http_inflight_requests` | gauge | service | concurrency |
| `tf_service_up` / `tf_latency_threshold_seconds` | gauge | service | health / threshold config visibility |

**Cardinality rule:** `route` is always the *template* (`/orders/{order_id}`), never the raw path. Trace IDs, request IDs and exception messages are never label values (tested: 500 distinct paths collapse to 1 label set).

## Logs

JSON lines on stdout: `timestamp, level, service, logger, message, trace_id, span_id, exception?`. `trace_id`/`span_id` are `null` (explicitly) when no valid span context exists. Sensitive headers are redacted (`test_redact_headers`).

**Limitation:** there is no central log backend in the demo; logs live in container stdout (`docker compose logs`). Trace correlation is emitted, but no UI joins logs to traces.

## Latency anomaly method

Static, configurable threshold (`TF_LATENCY_THRESHOLD_MS`, default 1000 ms) applied to each request's observed duration; breaches counted per route and visible as a span-adjacent signal. Deterministic in tests by construction.

- **Slow request** — one request exceeding the threshold (detector's classification).
- **Elevated latency percentile** — aggregate p95/p99 crossing an SLO (alert `TraceforgeHighLatency`); can fire without any single "slow" request or vice versa.
- **Anomalous request** — *not claimed*: no baseline learning or ML is implemented.

Tuning: start at p99 of normal traffic, keep above the slowest legitimate scenario, adjust per route in a real deployment.
