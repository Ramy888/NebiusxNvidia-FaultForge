# webhook-service (FaultForge example)

Handles `payment.succeeded` webhooks. Before marking an order paid it asks the payment provider
for the charge's status — but it never checks the HTTP status code and defaults a missing
`status` to `"succeeded"`. When the provider rate-limits the check (HTTP 429), the order is
marked **paid without any verification**. The happy-path tests here all pass.

```bash
uv run pytest
```
