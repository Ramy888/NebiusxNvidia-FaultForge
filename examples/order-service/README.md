# order-service (FaultForge example)

A tiny shop backend that places orders with an external fulfillment provider over HTTP.

It retries requests that time out — but it does not send an idempotency key, so when the provider
accepts an order and the response is lost, the retry creates a second fulfillment. FaultForge is
expected to find and repair this. The happy-path tests here all pass.

```bash
uv run pytest
```
