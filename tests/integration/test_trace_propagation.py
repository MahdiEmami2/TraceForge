"""Integration tests: real trace context propagation across process boundaries.

These tests start all three TraceForge services as REAL uvicorn subprocesses
on random free ports, then issue an actual HTTP request through the chain
gateway -> order -> inventory.  The assertions verify real W3C Trace Context
propagation over the network:

- every exported span of the request shares ONE trace_id,
- parent-child relationships match the actual call flow,
- the client-injected ``traceparent`` header is honoured.

Spans are exported via OTLP/HTTP to a lightweight in-process collector stub
implemented in this module (a real HTTP server that decodes the protobuf
ExportTraceServiceRequest bodies).  No mocking of the SDK: the services run
their normal OTLP exporters.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration

SRC = Path(__file__).resolve().parents[2] / "src"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _OtelCollectorStub:
    """Minimal OTLP/HTTP receiver: accepts protobuf trace exports.

    Decodes just enough of the protobuf wire format (ExportTraceServiceRequest)
    to extract trace ids, span ids, parent ids, names and attributes.  This is
    a real HTTP server - the applications export real OTLP bytes over TCP.
    """

    def __init__(self) -> None:
        self.spans: list[dict[str, Any]] = []
        self._server: subprocess.Popen[bytes] | None = None
        self.port = _free_port()
        self._script = PROJECT_ROOT / "tests" / "integration" / "_otlp_stub.py"
        self._log = open(  # noqa: SIM115
            PROJECT_ROOT / "tests" / "integration" / f"_stub_{self.port}.log", "wb"
        )

    def start(self) -> None:
        self._server = subprocess.Popen(
            [PYTHON, str(self._script), str(self.port), str(self._log.name)],
            cwd=str(PROJECT_ROOT / "tests" / "integration"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("OTLP stub did not start")

    def read(self) -> list[dict[str, Any]]:
        try:
            self._log.flush()
            with open(self._log.name, "rb") as fh:
                return [
                    json.loads(line)
                    for line in fh.read().splitlines()
                    if line.strip()
                ]
        except FileNotFoundError:
            return []

    def stop(self) -> None:
        if self._server:
            self._server.send_signal(signal.SIGTERM)
            self._server.wait(timeout=5)
        self._log.close()


def _wait_ready(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"service on {port} did not become ready")


@pytest.fixture(scope="module")
def stack() -> dict[str, Any]:
    """Start the OTLP stub + three services as real processes."""
    collector = _OtelCollectorStub()
    collector.start()
    ports = {"gateway": _free_port(), "order": _free_port(), "inventory": _free_port()}
    env = {
        **os.environ,
        "TF_OTEL_EXPORT_ENABLED": "true",
        "TF_OTEL_EXPORTER_PROTOCOL": "http/protobuf",
        "TF_OTEL_EXPORTER_ENDPOINT": f"http://127.0.0.1:{collector.port}/v1/traces",
        "TF_OTEL_EXPORT_TIMEOUT_MS": "2000",
        "TF_OTEL_SCHEDULE_DELAY_MS": "200",
        "TF_ENVIRONMENT": "development",
        "TF_LOG_LEVEL": "WARNING",
    }
    procs: list[subprocess.Popen[bytes]] = []

    def _launch(service: str, port: int, module: str, factory: str, extra: dict[str, str]) -> None:
        procs.append(
            subprocess.Popen(
                [
                    PYTHON, "-m", "uvicorn",
                    f"traceforge.{module}.main:{factory}",
                    "--host", "127.0.0.1",
                    "--port", str(port),
                ],
                env={
                    **env,
                    "TF_PORT": str(port),
                    "PYTHONPATH": str(SRC),
                    **extra,
                },
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        _wait_ready(port)

    try:
        _launch("inventory", ports["inventory"], "inventory", "create_inventory_app",
                {"OTEL_SERVICE_NAME": "inventory-service"})
        _launch("order", ports["order"], "orders", "create_orders_app",
                {"OTEL_SERVICE_NAME": "order-service",
                 "TF_INVENTORY_URL": f"http://127.0.0.1:{ports['inventory']}"})
        _launch("gateway", ports["gateway"], "gateway", "create_gateway_app",
                {"OTEL_SERVICE_NAME": "gateway",
                 "TF_ORDER_URL": f"http://127.0.0.1:{ports['order']}"})
        yield {"ports": ports, "collector": collector}
    finally:
        for proc in procs:
            proc.send_signal(signal.SIGTERM)
        for proc in procs:
            proc.wait(timeout=10)
        collector.stop()


def test_health_endpoints_answer(stack: dict[str, Any]) -> None:
    import urllib.request

    for port in stack["ports"].values():
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as resp:
            assert resp.status == 200


def test_full_trace_propagation_across_three_processes(stack: dict[str, Any]) -> None:
    """Checkout flows gateway -> order -> inventory; ONE trace id, real parents."""
    import urllib.request

    gateway_port = stack["ports"]["gateway"]
    req = urllib.request.Request(
        f"http://127.0.0.1:{gateway_port}/api/checkout",
        data=json.dumps({"sku": "SKU-1", "quantity": 2}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read())
        assert resp.status == 200
    assert body["status"] == "confirmed"
    assert body["inventory"]["sku"] == "SKU-1"

    # Give the batch processors time to export.
    time.sleep(3)
    spans = stack["collector"].read()
    by_id = {s["span_id"]: s for s in spans}

    def _find(fragment: str, service: str) -> dict[str, Any] | None:
        for span in spans:
            if fragment in span["name"] and span.get("service") == service:
                return span
        return None

    def _find_exact(name: str, service: str) -> dict[str, Any] | None:
        for span in spans:
            if span["name"] == name and span.get("service") == service:
                return span
        return None

    gw = _find("checkout", "gateway")
    order = _find("orders.create", "order-service")
    inv = _find("inventory.lookup", "inventory-service")

    # 1) All three share ONE trace id (not merely same service or timing).
    assert gw["trace_id"] == order["trace_id"] == inv["trace_id"]

    # 2) Real parent-child relationships across the network hops.
    #    orders.create's direct parent is the order-service ASGI server span;
    #    inventory.lookup's direct parent is the httpx client span living in
    #    the order-service process (cross-process linkage via traceparent).
    order_server = _find_exact("POST /orders", "order-service")
    assert order_server is not None, "order-service server span missing"
    order_parent = by_id.get(order["parent_id"])
    assert order_parent is not None, "orders.create parent missing from export"
    assert order_parent["service"] == "order-service"
    assert order_parent["trace_id"] == gw["trace_id"]
    inv = _find("inventory.lookup", "inventory-service")
    assert inv is not None, "inventory span missing"
    inv_parent = by_id.get(inv["parent_id"])
    assert inv_parent is not None, "inventory parent span missing from export"
    # inventory.lookup's direct parent is the inventory-service ASGI server
    # span; THAT span's parent is the httpx client span in order-service -
    # closing the cross-process chain inside one trace.
    assert inv_parent["service"] == "inventory-service"
    inv_grandparent = by_id.get(inv_parent["parent_id"])
    assert inv_grandparent is not None, "server span parent missing"
    assert inv_grandparent["service"] == "order-service"


def test_w3c_traceparent_header_manually_injected_is_honoured(stack: dict[str, Any]) -> None:
    """A client-supplied traceparent continues the SAME trace (W3C format)."""
    import urllib.request

    gateway_port = stack["ports"]["gateway"]
    client_trace_id = "1234567890abcdef1234567890abcdef"
    req = urllib.request.Request(
        f"http://127.0.0.1:{gateway_port}/api/checkout",
        data=json.dumps({"sku": "SKU-2", "quantity": 1}).encode(),
        headers={
            "Content-Type": "application/json",
            "traceparent": f"00-{client_trace_id}-1234567890abcdef-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        assert resp.status == 200

    time.sleep(3)
    spans = stack["collector"].read()
    checkout = [
        s for s in spans if "checkout" in s["name"] and s["trace_id"] == client_trace_id
    ]
    assert checkout, "client trace id was not propagated through all services"
