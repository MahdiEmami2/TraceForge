# Security

- **Fault injection** (`/inventory/scenario*`) is active only when `TF_ENVIRONMENT=development` **and** `TF_FAULT_INJECTION_ENABLED=true`; production configs with injection enabled fail validation at startup (`test_fault_injection_forbidden_in_production`). No arbitrary code execution exists anywhere in the codebase — scenarios are a closed enum (`KNOWN_SCENARIOS`).
- **Input validation:** Pydantic models bound `sku` (1–64 chars) and `quantity` (1–1000); FastAPI rejects anything else with 422.
- **Secrets:** none in source; `.env` is gitignored, `.env.example` contains only non-secret defaults. Runtime expects no credentials at all.
- **Telemetry privacy:** span attributes carry SKUs and scenario names, never credentials, headers, or user payloads. `redact_headers` drops `Cookie`/`Set-Cookie` and masks `Authorization`/`X-Api-Key` before anything is logged. Exception logs contain stack traces but not request bodies.
- **Safe errors:** the global handler returns `{"detail": "internal error"}` — no internals leak; `X-Content-Type-Options: nosniff` on every response.
- **CORS:** no CORS middleware is enabled. The gateway is intended for server-to-server/curl use; adding browser origins would require an explicit allowlist (documented as a future improvement, not shipped silently permissive).
- **Limits:** payload size is bounded by Pydantic constraints; no upload endpoints exist. Production deployments should front the gateway with a reverse proxy for rate limiting and TLS.
- **Containers:** the app image runs as non-root `appuser`; Grafana runs anonymous-admin **for local development only** — never expose port 3000 publicly.
- **Config distinction:** `TF_ENVIRONMENT=production` disables fault injection by default and hard-fails on unsafe overrides; all other defaults are development-safe.
