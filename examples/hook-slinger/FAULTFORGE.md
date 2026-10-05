# hook-slinger (third-party example)

Upstream: https://github.com/rednafi/hook-slinger at commit `48c19db` (MIT, see `LICENSE`).
The application code (`app/`, `config.py`, `requirements.txt`) is copied **unchanged**.

Left out on purpose:

- `tests/test_integration.py` — needs a running hook-slinger server and Redis.
- `tests/test_views.py` — its token-security tests depend on the local environment.
- Docker, docs and CI files.

The bug FaultForge looks for is upstream's own, not planted: `send_post_request` treats any
response other than `200 OK` as a failure and the job is retried by rq, with no idempotency key —
so a receiver that answers `202 Accepted`, or one whose response times out after processing,
receives the same webhook again.

Requirements: Python 3.11 (pinned dependencies predate 3.12) and its packages, so it runs only in
Token Factory Sandboxes:

```bash
uv run --extra contree --env-file .env faultforge run examples/hook-slinger \
  --sandbox contree --image python:3.11-slim \
  --setup "python -m pip install -q -r requirements.txt pytest"
```
