# Decision Records

| # | Decision | Rationale | Source of the pin |
|---|---|---|---|
| 1 | Trace backend: **Grafana Tempo 3.1.0** | Native OTLP ingest (no app-side conversion), single binary, local parquet storage, first-class Grafana "Trace to metrics" linking; Jaeger would need an extra OTLP-span-storage mapping layer. | Tag `3.1.0` verified on Docker Hub (`grafana/tempo`); release page github.com/grafana/tempo/releases |
| 2 | Collector image: **otel/opentelemetry-collector:0.139.0** (core, not contrib) | Core distribution covers OTLP receiver, batch processor, OTLP exporter, health_check extension — nothing contrib-only is used. | Tag verified on Docker Hub API query `name=0.139` |
| 3 | Prometheus **v3.13.4**, Grafana **12.1.4**, Python base **3.12-slim** | Newest stable patch lines found on Docker Hub at build time (2026-10-19). | Docker Hub tag listings |
| 4 | OTel SDK **1.39.1** + instrumentation **0.60b1** | Same release train pairing (0.xx(b) instrumentation tracks 1.xx SDK); all wheels installable on Python 3.12. | `pip index versions` (mainline packages 1.45.1 shown; 1.39.1/0.60b1 chosen after the 1.45-line's FastAPI/HTTPX instrumentation packages failed to install on Python 3.12 in this environment — recorded honestly) |
| 5 | Metrics via `prometheus-client` on `/metrics`, not OTel metric export | Prometheus scraping is the native path; avoids a second push pipeline and Collector metric-state complexity for the demo. | — |
| 6 | Logs to stdout only (no Loki) | Keeps the stack to one telemetry storage system (Tempo); a local log backend would add notable RAM for little demo value. Correlation fields are still emitted. | — |
| 7 | Static-threshold latency detector (no ML) | Requirement: transparent, deterministic, testable. Baseline/ML detection is explicitly out of scope and not claimed. | — |
| 8 | Integration tests use real uvicorn subprocesses + real OTLP to an HTTP stub | Docker unavailable; this still validates the true wire path (protobuf over TCP, real propagation) instead of mocking the SDK. | PLAN.md environment findings |
| 9 | Bounded metric labels (`route` template, no trace ids) | Prevents Prometheus cardinality explosions; verified by test. | — |
