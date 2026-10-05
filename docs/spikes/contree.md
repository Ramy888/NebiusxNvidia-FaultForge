# Spike: Token Factory Sandboxes (Contree)

**Status: verified live on 2026-10-05 — upload, run, branch isolation and follow-up runs all work** (`tests/sandbox/test_contree_live.py`).

Previously: beta access requested 2026-10-04 (Token Factory console → Sandboxes → Request beta access). Credentials are verified: a real call returns 403 Forbidden (not enabled yet), not 401.**

Sandboxes use the **same Nebius API key and project ID** as inference: `NEBIUS_API_KEY` and `NEBIUS_PROJECT_ID`. No separate token or `contree auth` is needed.

## What the SDK showed (contree-sdk 0.3.6, inspected 2026-10-03)

- `ContreeSync()` reads credentials from `contree auth` (`~/.config/contree/auth.ini`).
- `images.use(tag_or_uuid)` returns an image; `image.run(shell=..., cwd=..., files=..., timeout=..., disposable=False).wait()` runs a command and yields a **new image** with `uuid`, `stdout`, `stderr`, `exit_code`.
- `disposable=True` is the default and discards the result image — FaultForge passes `False` so candidates and scenarios can branch from it.
- `files` maps absolute image paths to `bytes` (contents) or `str`/`Path` (a *local path* to upload). FaultForge always sends bytes.
- `image.apply_files(files=...)` bakes files into a new image — used to upload the repo.
- Timeouts raise `OperationTimedOutError` / `ApiTimeoutError`; FaultForge reports them as timed-out runs.

## Still to confirm live

```bash
FAULTFORGE_LIVE_CONTREE=1 uv run --extra contree --env-file .env pytest tests/sandbox/test_contree_live.py
```

1. Is `python:3.12-slim` available via `images.use`, or must it be imported first (`images.oci(...)`)?
2. ~~Does `apply_files` need `.wait()`?~~ No: it returns an already-SUCCEEDED image, and `wait()` on it raises. Only PREPARING/PREPARED images can be waited on.
3. Is outbound network on by default (needed for `pip install httpx pytest` in the setup step)? If not, build a base image with them preinstalled.
4. Real per-run latency — decides how many branches the demo can afford to run in parallel (cap: 50 concurrent operations).
