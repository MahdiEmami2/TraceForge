# Operations

## Start (PowerShell, from the project root)

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose ps                # wait for all services healthy
curl http://localhost:8080/healthz
```

## Stop / reset

```powershell
docker compose down              # keep data volumes
docker compose down -v           # also remove tempo/prometheus/grafana data
```

## URLs (from docker-compose.yml)

| Service | URL |
|---|---|
| Gateway API | http://localhost:8080 |
| Grafana | http://localhost:3000 (anonymous admin, local only) |
| Prometheus | http://localhost:9090 |
| Tempo API | http://localhost:3200 |
| Collector OTLP | localhost:4317 (gRPC) / 4318 (HTTP); health :13133 |
| Order/Inventory | internal only (compose DNS names) |

## Demo scenarios (development only)

```powershell
# normal
curl -X POST http://localhost:8080/api/checkout -H "Content-Type: application/json" -d '{"sku":"SKU-1","quantity":2}'

# slow downstream (~1.5 s) — then investigate the trace in Grafana
curl -X POST http://localhost:8000/api/inventory-lookup -H "Content-Type: application/json"  # via gateway:
curl "http://localhost:8080/api/inventory-lookup?sku=SKU-1"
curl -X POST http://localhost:8080/api/inventory/scenario -H "Content-Type: application/json" -d '{"scenario":"slow"}'
# NOTE: scenario endpoints live on the inventory service; port-forward or exec:
docker compose exec -T inventory-service true   # see README for direct-scenario variant
```

Scenario endpoints exist on `inventory-service` (`POST /inventory/scenario`, `DELETE /inventory/scenario`). From the host, reach them through a one-off container or temporarily publish port 8000 of `inventory-service` in `docker-compose.yml`.

## Troubleshooting

| Symptom | Check |
|---|---|
| Traces missing | `docker compose logs otel-collector`; `tf_otel_export_failures_total > 0` means apps could not export; Collector → Tempo endpoint is `tempo:4317` |
| Prometheus target DOWN | `docker compose ps`, app healthcheck; scrape config at `prometheus/prometheus.yml` |
| Grafana empty | data sources provisioned to `prometheus:9090` / `tempo:3200`; generate traffic first |
| Tempo "no traces" | volume `tempo-data` must be writable; retention 24 h |
| App returns 502/503 | intentional scenario active — clear with `DELETE /inventory/scenario` |

**Do not assume** a 200 from `/api/checkout` proves telemetry was exported — always check Tempo/Grafana (verified correlation steps in README).
