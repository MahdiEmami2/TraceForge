# Trace Context

## Propagation

W3C Trace Context (`traceparent`) is the single propagation format. Incoming server spans extract it (FastAPI instrumentation); outgoing httpx client spans inject it (HTTPX instrumentation wired in the shared app factory).

Verified in `tests/integration/test_trace_propagation.py` with three **real uvicorn processes**:

- `test_full_trace_propagation_across_three_processes` — decodes real OTLP exports from all three services and asserts a **shared trace id** plus parent-child linkage (inventory span ← inventory server span ← order-service client span; `orders.create` ← order-service server span — all in one trace).
- `test_w3c_traceparent_header_manually_injected_is_honoured` — a client-supplied `traceparent` with a fixed trace id propagates through all three services unchanged.

A historical defect is recorded in PLAN.md: before HTTPX instrumentation was wired, the order service started *unrelated* traces; the integration test caught this and the fix was verified by re-running.

## Span hierarchy for `POST /api/checkout`

```
gateway: POST /api/checkout (SERVER, root)
└── gateway.checkout (INTERNAL)
    └── POST http://order-service:8000/orders (CLIENT)
        └── order-service: POST /orders (SERVER)
            └── orders.create (INTERNAL)
                └── GET http://inventory-service:8000/inventory (CLIENT)
                    └── inventory-service: GET /inventory (SERVER)
                        └── inventory.lookup (INTERNAL)
```

## Failure representation

- Connection errors: `httpx.RequestError` recorded via `span.record_exception`, span status ERROR, counted in `tf_downstream_failures_total` with `kind=<exception name>`.
- HTTP failures: status attribute set, span status ERROR, kind `http-<code>`.
- Unhandled exceptions: recorded by the SDK, logged with stack trace, safe 500 response.
