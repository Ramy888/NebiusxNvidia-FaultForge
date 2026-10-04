# Spike: Token Factory + Nemotron

**Status: verified live on 2026-10-04 — all checks pass.**

Run:

```bash
uv run --env-file .env python scripts/spike_token_factory.py
```

Questions it answers, per role (plan = Ultra, write = Nano):

1. Does the configured base URL answer for that model? (The us-central1 URL came from a search summary, not the docs.)
2. Is reasoning returned inside `content` as `<think>` tags, or in a separate field? `parse_json` handles both; the client only reads `content`.
3. Does `response_format={"type": "json_object"}` work alongside reasoning? If yes, set `TF_JSON_MODE=1`.
4. Does tool calling work? FaultForge does not depend on it.

## Results

| Check | Result | Time | Detail |
|---|---|---|---|
| plan answers (`nvidia/Nemotron-3-Ultra-550b-a55b` @ `api.tokenfactory.us-central1.nebius.com/v1`) | ok | 1.9s | reasoning returned in a separate field, `content` is clean; 37/100 tokens |
| plan JSON mode | ok | 0.5s | valid JSON |
| plan tool calling | ok | 2.1s | called `record_strategy` |
| write answers (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` @ `api.tokenfactory.nebius.com/v1`) | ok | 1.6s | no reasoning field; 37/113 tokens |
| write JSON mode | ok | 0.8s | valid JSON |
| write tool calling | ok | 1.4s | called `record_strategy` |

Conclusions:
- The region split is real and the configured base URLs are correct.
- JSON mode works on both roles, so `TF_JSON_MODE=1` is the recommended setting.
- Tool calling works too, but FaultForge keeps the JSON contract (simpler, already validated).
