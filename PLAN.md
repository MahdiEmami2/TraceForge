# TraceForge Implementation Plan

## Environment findings (verified 2026-10-19)

| Check | Result |
|---|---|
| Workspace | Empty sandbox `/home/user` (no pre-existing repo; `git status` → "not a git repository") |
| Python | 3.12.3 (`python3 --version`) |
| Docker | **NOT AVAILABLE** (`docker`: command not found; no docker compose) |
| pip network | Working — all packages installed from PyPI |
| Git binary | Available (2.43.0) but no repo initialized (sandbox limitation, init not persisted) |

**Consequence:** the full Docker Compose stack (Collector, Tempo, Prometheus, Grafana)
could NOT be started or observed in this environment. Every claim about stack
behavior is therefore labeled *unverified* in the completion report. Tests that
require Docker are not faked: integration coverage instead runs all three services
as real uvicorn subprocesses exporting real OTLP to a real HTTP receiver.

## Acceptance criteria (see docs/ACCEPTANCE_CRITERIA.md)

1. Three separately identifiable FastAPI services with real HTTP hops. — **Done**
2. W3C traceparent propagation across processes, one trace id per request,
   correct parent-child spans. — **Done, verified by integration tests**
3. OTLP Collector → Tempo pipeline configured. — **Config written; runtime unverified (no Docker)**
4. Prometheus scrape config + alert rules. — **Config written; scraping unverified (no Docker)**
5. Grafana provisioning + dashboard. — **JSON written; rendering unverified (no Docker)**
6. Trace-correlated structured JSON logs. — **Done, unit-tested**
7. Static latency threshold detector. — **Done, unit-tested**
8. Fault-injection scenarios gated to development. — **Done, tested incl. production lockout**
9. pytest suite (unit + integration), ruff, mypy, config validation. — **Done, 47/47 pass**
10. Release ZIP `dist/TraceForge.zip`, validated. — **Done**

## Checkpoints

- [x] Stage 1: environment probe, dependency pins verified against real registries
- [x] Stage 2: core library (config, scenarios, telemetry, logging, metrics, detector)
- [x] Stage 3: three services + app factory; first test run 18 failed → root causes fixed
- [x] Stage 4: integration harness (real processes + OTLP stub); caught missing httpx
      instrumentation (real defect: traces split across services) → fixed → 47/47 green
- [x] Stage 5: infrastructure configs (compose, collector, tempo, prometheus, grafana)
- [x] Stage 6: docs, CI, release packaging

## Defects found by tests and fixed (log kept per engineering rules)

1. Wrong OTLP exporter import paths for opentelemetry 1.39/0.60b1 — fixed.
2. `BatchLogRecordExporter` renamed → `BatchLogRecordProcessor` in current SDK — fixed.
3. Fault-injection semantics: production could previously be configured with
   injection enabled if flag explicitly set; now dev-by-default + hard validation error.
4. Metrics middleware crashed on FastAPI's `route.matches()` (scope missing `method`);
   cardinality test then exposed that raw paths were recorded before the fix path was
   wired — both fixed; template collapse now verified.
5. **Real tracing defect:** outgoing httpx calls were not instrumented, so the
   `traceparent` header was never injected and the Order Service started an unrelated
   trace (caught by `test_full_trace_propagation_across_three_processes`) — fixed by
   instrumenting `HTTPXClientInstrumentor` in the app factory.
