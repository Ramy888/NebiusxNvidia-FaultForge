# Example repositories

Small, self-contained Python backends used to demonstrate FaultForge. Each one's own tests pass;
each hides a realistic dependency-failure bug that only shows up under an injected fault.

| Example | Dependency | Hidden failure | Fault that exposes it |
|---|---|---|---|
| [order-service](order-service) | fulfillment provider (POST) | retries a timed-out request without an idempotency key → duplicate fulfillment | timeout after processing |
| [webhook-service](webhook-service) | payment provider (GET charge) | ignores the HTTP status and defaults to `"succeeded"` → unpaid order marked paid | rate limit (429) |
| [hook-slinger](hook-slinger) — **third-party**, [rednafi/hook-slinger](https://github.com/rednafi/hook-slinger), unchanged | webhook receivers (POST) | deliveries carry no idempotency key, so retries and duplicates are processed twice; any non-`200` (even `201`/`202`) counts as failure and is retried | duplicate delivery, timeout |

Run either offline: `uv run faultforge demo --example webhook-service`.

hook-slinger needs Python 3.11 and its pinned packages, so it runs in Token Factory Sandboxes
(see [hook-slinger/FAULTFORGE.md](hook-slinger/FAULTFORGE.md)). It creates its own `httpx.Client`
inside the function, so FaultForge's tests inject faults with pytest's monkeypatch.
