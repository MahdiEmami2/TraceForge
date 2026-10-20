"""Minimal OTLP/HTTP trace receiver stub used by integration tests.

Listens on 127.0.0.1:<port>, accepts POST /v1/traces with protobuf
ExportTraceServiceRequest payloads and appends one JSON line per span
to a log file.  Decodes the payload with the REAL OpenTelemetry protobuf
definitions (opentelemetry-proto package) - the services export genuine
OTLP bytes over TCP; nothing about the wire format is mocked.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)


def dump_spans(payload: bytes, log_path: str) -> None:
    request = ExportTraceServiceRequest()
    request.ParseFromString(payload)
    with open(log_path, "a", encoding="utf-8") as fh:
        for resource_spans in request.resource_spans:
            service = "unknown"
            for attr in resource_spans.resource.attributes:
                if attr.key == "service.name":
                    service = attr.value.string_value
            for scope_spans in resource_spans.scope_spans:
                for span in scope_spans.spans:
                    parent = (
                        span.parent_span_id.hex()
                        if span.parent_span_id and set(span.parent_span_id.hex()) != {"0"}
                        else None
                    )
                    fh.write(
                        json.dumps(
                            {
                                "service": service,
                                "trace_id": span.trace_id.hex(),
                                "span_id": span.span_id.hex(),
                                "parent_id": parent,
                                "name": span.name,
                                "start_unix_nano": span.start_time_unix_nano,
                                "end_unix_nano": span.end_time_unix_nano,
                                "status_code": span.status.code,
                                "attributes": {
                                    a.key: getattr(a.value, a.value.WhichOneof("value"), None)
                                    for a in span.attributes
                                },
                            }
                        )
                        + "\n"
                    )


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        log_path = self.server.log_path  # type: ignore[attr-defined]
        try:
            dump_spans(body, log_path)
        except Exception as exc:  # noqa: BLE001
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"error": str(exc)}) + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: object) -> None:  # silence
        return


if __name__ == "__main__":
    port = int(sys.argv[1])
    log_path = sys.argv[2]
    server = HTTPServer(("127.0.0.1", port), Handler)
    server.log_path = log_path  # type: ignore[attr-defined]
    server.serve_forever()
