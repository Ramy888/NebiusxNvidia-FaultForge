# FaultForge — Spec

Source: the FaultForge brief and design decisions of 2026-10-02. This file records them; it adds no new requirements.

## Promise

"Find out how your application fails when its dependencies misbehave — and get a repair tested against those failures."

## Users

Developers on small backend teams who own a Python service that calls external HTTP dependencies.

## Core flow

A developer selects a small Python backend repository and a critical operation (for example creating an order or processing a webhook). The agent:

1. Runs the application's normal tests.
2. Identifies an external HTTP dependency and proposes relevant failure scenarios.
3. Writes executable tests for timeouts, rate limits, malformed responses and duplicate delivery.
4. Runs each scenario in a separate sandbox branch.
5. Generates candidate repairs for a reproduced failure.
6. Replays the same scenarios against each repair and produces a PR with the evidence.

## Flagship demo

A fake fulfillment service accepts an order, but its response times out. The application retries and creates a duplicate. The agent generates a test asserting that one user operation creates only one order, then repairs the retry/idempotency logic.

The screen shows: the dependency and injected failure; the actual incorrect result; competing repair attempts; before-and-after results for the same scenarios; the patch and regression test.

## Scope boundary

- One backend language: Python. Target apps call dependencies through `httpx`.
- HTTP dependencies only. Four fault types: timeout, rate limit, malformed response, duplicate delivery.
- Two or three example repositories, at least one third-party.
- Faults injected at the HTTP-client transport layer (deterministic). A separate fake service is stretch only.
- Out of scope: full network simulation, Kubernetes, other languages.
- Do not claim to have invented chaos/fault-injection testing. The distinction is the integrated reproduce → repair → replayed-verification loop.

## Platform requirements (hackathon)

- Inference on Nebius Token Factory with NVIDIA Nemotron models (Ultra for planning/analysis, Nano for writing tests and patches).
- Code runs in Nebius Token Factory Sandboxes (Contree); branching = several runs from one image.
- A runtime Tavily call (documented dependency failure/retry behaviour) for the Tavily bonus.
- Public repo with an OSS licence (MIT), README with setup/run and a section on how Nemotron and Token Factory are used.
- Public demo URL that runs prepared repos only, with turn, time, concurrency and rate limits.

## Non-functional

- Everything up to the repair-and-replay loop runs offline with a stub LLM and a local sandbox.
- Model output is consumed as structured JSON; patches outside the repo root are refused.
- Every sandbox run has a timeout; temporary resources are cleaned up in `finally`.
