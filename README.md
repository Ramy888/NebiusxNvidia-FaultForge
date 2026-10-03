# FaultForge

**Find out how your application fails when its dependencies misbehave — and get a repair tested against those failures.**

FaultForge takes a small Python backend and one critical operation (creating an order, processing a webhook). It injects realistic dependency failures — timeouts, rate limits, malformed responses, duplicate delivery — reproduces what actually breaks, generates competing repairs, and replays every failure against every repair before proposing a pull request with the evidence.

Built for the Nebius x NVIDIA Global AI Hackathon (Coding & Agentic Engineering track).

## How it works

1. Run the application's normal tests.
2. Find an external HTTP dependency and propose failure scenarios.
3. Write executable tests for each failure.
4. Run each scenario in its own sandbox branch.
5. Generate candidate repairs for a reproduced failure.
6. Replay the same scenarios against every repair; open a PR with the evidence.

## How Nemotron and Token Factory are used

_To be completed as the integration lands._

- **Nemotron 3 Ultra** — analysis and planning.
- **Nemotron 3 Nano** — writing failure tests and candidate patches.
- **Token Factory Sandboxes** — every scenario and every repair runs in its own branch from one checkpoint.

## Setup

```bash
uv sync
cp .env.example .env   # fill in keys for live mode; offline mode needs none
uv run pytest
```

## Licence

MIT — see [LICENSE](LICENSE).
