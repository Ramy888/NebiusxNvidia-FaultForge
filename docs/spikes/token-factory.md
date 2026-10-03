# Spike: Token Factory + Nemotron

**Status: pending — needs `NEBIUS_API_KEY` in `.env`.**

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

_Paste the script's table here after the first live run._
