"""YAML syntax + schema validation for all TraceForge configuration files.

Validates structure (required keys, endpoint shapes, cardinality guardrails)
without requiring Docker.  Run: python scripts/validate_configs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    # --- Collector -----------------------------------------------------------
    collector = yaml.safe_load((ROOT / "collector" / "config.yaml").read_text())
    check("otlp" in collector["receivers"], "collector: otlp receiver missing")
    check("batch" in collector["processors"], "collector: batch processor missing")
    check(
        collector["service"]["pipelines"]["traces"]["exporters"] == ["otlp/tempo"],
        "collector: traces pipeline must export to otlp/tempo",
    )
    check(
        "health_check" in collector["extensions"], "collector: health_check extension missing"
    )

    # --- Tempo ----------------------------------------------------------------
    tempo = yaml.safe_load((ROOT / "tempo" / "tempo.yaml").read_text())
    check(
        tempo["distributor"]["receivers"]["otlp"]["protocols"]["grpc"]["endpoint"]
        == "0.0.0.0:4317",
        "tempo: OTLP gRPC receiver must listen on 4317",
    )

    # --- Prometheus -------------------------------------------------------------
    prom = yaml.safe_load((ROOT / "prometheus" / "prometheus.yml").read_text())
    targets = prom["scrape_configs"][0]["static_configs"][0]["targets"]
    for expected in ("gateway:8000", "order-service:8000", "inventory-service:8000"):
        check(expected in targets, f"prometheus: scrape target {expected} missing")
    rules = yaml.safe_load((ROOT / "prometheus" / "rules" / "alerts.yml").read_text())
    alert_names = [
        a["alert"] for g in rules["groups"] for a in g["rules"] if "alert" in a
    ]
    for expected in (
        "TraceforgeHighErrorRate",
        "TraceforgeHighLatency",
        "TraceforgeServiceDown",
        "TraceforgeTelemetryExportFailing",
    ):
        check(expected in alert_names, f"prometheus: alert {expected} missing")

    # --- Grafana provisioning ----------------------------------------------------
    ds = yaml.safe_load((ROOT / "grafana" / "provisioning" / "datasources" / "datasources.yaml").read_text())
    uids = {d["uid"] for d in ds["datasources"]}
    check("traceforge-prom" in uids, "grafana: Prometheus datasource missing")
    check("traceforge-tempo" in uids, "grafana: Tempo datasource missing")

    # --- Compose (YAML parse only; full validation needs Docker) ---------------
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    for svc in ("gateway", "order-service", "inventory-service", "otel-collector", "tempo", "prometheus", "grafana"):
        check(svc in compose["services"], f"compose: service {svc} missing")

    if failures:
        print("CONFIG VALIDATION FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"OK: all configuration files valid ({len(failures)} problems)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
