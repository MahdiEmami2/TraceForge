# Alerting

Rules: `prometheus/rules/alerts.yml` (loaded by Prometheus, evaluated every 5 s locally).

| Alert | Expression (summary) | For | Severity | How to trigger (dev) |
|---|---|---|---|---|
| `TraceforgeHighErrorRate` | 5xx rate / request rate > 10 % | 2 m | warning | `POST /inventory/inventory/scenario {"scenario":"error"}` then load `/inventory?sku=SKU-1` |
| `TraceforgeHighLatency` | p95 > 1 s | 2 m | warning | set scenario `slow` or `threshold`, then load `/inventory` |
| `TraceforgeLatencyThresholdBreaches` | breach counter rate > 0.2/s | 1 m | warning | same as above (per-request detector) |
| `TraceforgeDownstreamFailures` | >5 failures / 5 m | — | warning | set scenario `unavailable`, then `GET /api/inventory-lookup?sku=SKU-1` via gateway |
| `TraceforgeServiceDown` | `tf_service_up == 0` | 30 s | critical | `docker compose stop inventory-service` |
| `TraceforgeScrapeTargetMissing` | `up{job="traceforge-apps"} == 0` | 1 m | critical | stop any app container |
| `TraceforgeTelemetryExportFailing` | >3 export failures / 10 m | — | warning | stop the Collector (`docker compose stop otel-collector`) and generate traffic |

**Limitation (honest):** alert *evaluation* happens in Prometheus and is visible at http://localhost:9090/alerts and in Grafana. **No notification channel** (email/Slack/PagerDuty) is configured — Alertmanager is intentionally not part of the stack, so nothing pages anyone. Steps above reproduce the conditions; the firing behavior itself was not observed because Docker was unavailable in the build environment (see ACCEPTANCE_CRITERIA.md).
