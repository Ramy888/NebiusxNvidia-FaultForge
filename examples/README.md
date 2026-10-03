# Example repositories

Small, self-contained Python backends used to demonstrate FaultForge. Each one's own tests pass;
each hides a realistic dependency-failure bug that only shows up under an injected fault.

| Example | Dependency | Hidden failure | Fault that exposes it |
|---|---|---|---|
| [order-service](order-service) | fulfillment provider (POST) | retries a timed-out request without an idempotency key → duplicate fulfillment | timeout after processing |
| [webhook-service](webhook-service) | payment provider (GET charge) | ignores the HTTP status and defaults to `"succeeded"` → unpaid order marked paid | rate limit (429) |

Run either offline: `uv run faultforge demo --example webhook-service`.

A third, third-party open-source repository is still to be chosen (it must call its dependency
through `httpx` with an injectable client).
