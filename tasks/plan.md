# Implementation Plan: FaultForge

## Overview

FaultForge shows a developer how their backend fails when an HTTP dependency misbehaves, then produces a repair that is verified against those same failures. Given a small Python repo and a critical operation, it runs the normal tests, proposes failure scenarios for one dependency (timeout, rate limit, malformed response, duplicate delivery), writes executable tests for them, runs each in its own sandbox branch, generates competing repairs for a reproduced failure, replays every scenario against every repair, and outputs a PR with the evidence.

Hackathon: Nebius x NVIDIA, Coding & Agentic Engineering track. Deadline **Oct 30, 2026 19:00 Cairo** (submit Oct 29). Oct 17–23 is kept light.

## Architecture Decisions

- **Python only, HTTP dependencies only, four fault types.** Target apps must call their dependency through `httpx` with an injectable client/transport. Anything else is out of scope.
- **Faults are injected at the HTTP-client transport layer** (`httpx.MockTransport`-style), not through a separate fake service. Deterministic, no real sleeps, no networking inside the sandbox, and each scenario is one `pytest` invocation. A standalone fake service is stretch only.
- **Sandbox behind an interface.** `Sandbox.run(snapshot, command, files) -> RunResult(snapshot, exit_code, stdout, stderr)`. Every run returns a new snapshot, mirroring Contree's `image.run()` → new image `uuid`; branching is several runs from one snapshot. `LocalSandbox` (temp-dir copy + subprocess) first, `ContreeSandbox` when credentials arrive.
- **LLM behind an interface.** `StubLLM` for offline tests; `TokenFactoryLLM` holds two OpenAI-compatible clients because Nemotron models are region-scoped (Nano/Lightning eu-north1, Super/Ultra us-central1). Ultra plans and analyses; Nano writes tests and patches.
- **Structured JSON output is the contract with the model**, not tool calling — Nemotron tool-calling support on Token Factory is unconfirmed.
- **The pipeline emits events** (`scenario_started`, `run_finished`, `repair_proposed`, …). The CLI report, the API's SSE stream and the UI's attempt tree all consume the same event log.
- **Build the repair-and-replay loop before scenario generation.** It is the submittable fallback; if free-form generation is not stable by Oct 16, scenarios ship as templates.
- **Public demo runs prepared repos only**, with turn, time, concurrency and rate limits. It executes model-written code, so this is a security surface.

## Layout

```
faultforge/
  events.py        # event types + in-memory/JSONL log
  faultkit/        # the four faults as an httpx transport; copied into the sandbox
  sandbox/         # base.py (protocol), local.py, contree.py
  llm/             # base.py (protocol), stub.py, token_factory.py
  scenarios.py     # Scenario model, templates, generation, validation
  repair.py        # candidate generation + patch application
  replay.py        # scenarios × candidates matrix, scoring
  research.py      # Tavily lookup of documented dependency behaviour
  pipeline.py      # orchestration
  cli.py           # `faultforge run <repo>`
  api.py           # FastAPI + SSE
web/               # UI
examples/order-service/   # planted retry-on-timeout duplicate bug
tests/
```

## Dependency Graph

```
example repo (T2) ──► faultkit + failing scenario (T3)
                              │
sandbox protocol + local (T4) ┤
                              ▼
                      replay matrix (T5) ◄── LLM protocol + stub + repair (T6)
                              │
                         CLI end-to-end (T7)          ── fallback is submittable here
                              │
   Token Factory spike (T8) ──┼── Contree sandbox (T9)
                              ▼
                     live repair loop (T10)
                              │
        discovery (T11) ► scenario generation (T12) ► Tavily (T13) ► more repos (T14)
                              │
              API + events (T15) ► UI tree (T16) ► UI evidence (T17) ► PR (T18)
                              │
                  demo limits (T19) ► deploy (T20) ► submission (T21–T22)
```

## Task List

### Phase 0: Foundation (offline)

#### Task 1: Project scaffold and gates — S
**Description:** uv project, package skeleton, MIT `LICENSE`, `.env.example`, README skeleton with a stubbed "How Nemotron and Token Factory are used" section, ruff + pytest configured.
**Acceptance criteria:**
- [ ] `uv sync` succeeds on a clean clone
- [ ] `LICENSE` is at the repo root; `.env.example` lists every variable with no values
- [ ] One trivial test passes
**Verification:** `uv run pytest -q` · `uv run ruff check .`
**Dependencies:** None
**Files:** `pyproject.toml`, `LICENSE`, `.env.example`, `README.md`, `faultforge/__init__.py`, `tests/test_smoke.py`

#### Task 2: Example order service with the planted bug — S
**Description:** A minimal order service (`create_order`) that calls a fulfillment API through an injectable `httpx.Client` and retries on timeout without an idempotency key. Its own tests cover only the happy path and pass.
**Acceptance criteria:**
- [ ] Happy-path tests pass
- [ ] The retry path exists and has no idempotency protection
- [ ] The service has no dependency on FaultForge
**Verification:** `cd examples/order-service && uv run pytest -q`
**Dependencies:** T1
**Files:** `examples/order-service/{pyproject.toml,orders/service.py,orders/fulfillment.py,tests/test_orders.py,README.md}`

#### Task 3: Faultkit and the hand-written failing scenario — M
**Description:** The four fault types as a deterministic httpx transport, plus one hand-written scenario test: "fulfillment accepts the order but the response times out; one user operation must create exactly one order".
**Acceptance criteria:**
- [ ] Timeout, rate limit (429 + `Retry-After`), malformed JSON and duplicate delivery each have a unit test
- [ ] No fault uses a real sleep; the whole suite runs in under 2 s
- [ ] The duplicate-order scenario FAILS against the example service with a message naming two orders
**Verification:** `uv run pytest tests/faultkit -q` · scenario test fails with the expected assertion
**Dependencies:** T2
**Files:** `faultforge/faultkit/{__init__.py,transport.py,faults.py}`, `tests/faultkit/test_faults.py`, `tests/fixtures/scenarios/timeout_duplicate.py`

### Checkpoint A: bug reproduced
- [ ] Planted bug is reproduced deterministically on a clean clone
- [ ] All gates green

### Phase 1: Repair and replay (offline, the fallback product)

#### Task 4: Sandbox protocol and LocalSandbox — M
**Description:** The `Sandbox` protocol and a local implementation where a snapshot is a directory copy. Runs have a timeout and their temp dirs are cleaned up in `finally`.
**Acceptance criteria:**
- [ ] Two runs from one snapshot do not see each other's file changes
- [ ] A run that exceeds its timeout is killed and reported, not hung
- [ ] Temp directories are removed on success and on failure
**Verification:** `uv run pytest tests/sandbox -q`
**Dependencies:** T1
**Files:** `faultforge/sandbox/{base.py,local.py}`, `tests/sandbox/test_local.py`

#### Task 5: Replay matrix and scoring — M
**Description:** Run every scenario against the baseline and against each candidate patch in separate branches, parse junit results, and score candidates (scenarios fixed, existing tests still passing, diff size).
**Acceptance criteria:**
- [ ] With fixture patches, the correct idempotency patch ranks first and a patch that just removes retries ranks below it
- [ ] A patch that breaks the existing tests is rejected
- [ ] The output records before/after per scenario
**Verification:** `uv run pytest tests/test_replay.py -q`
**Dependencies:** T3, T4
**Files:** `faultforge/replay.py`, `faultforge/events.py`, `tests/test_replay.py`, `tests/fixtures/patches/*.diff`

#### Task 6: LLM protocol, stub and repair generation — M
**Description:** `LLM` protocol with a role parameter (`plan` / `write`), a `StubLLM` returning canned JSON, and `repair.py`, which asks for N candidate patches as structured JSON and applies them safely.
**Acceptance criteria:**
- [ ] Malformed model output is rejected with a clear error and retried once
- [ ] A patch touching files outside the repo root is refused
- [ ] With the stub, N candidates come back as applicable patches
**Verification:** `uv run pytest tests/test_repair.py -q`
**Dependencies:** T1
**Files:** `faultforge/llm/{base.py,stub.py}`, `faultforge/repair.py`, `tests/test_repair.py`

#### Task 7: CLI end-to-end on the example repo — S
**Description:** `faultforge run examples/order-service --scenario timeout_duplicate` wires pipeline → events → a markdown evidence report.
**Acceptance criteria:**
- [ ] One command goes from red scenario to a ranked repair using the stub LLM, with no network
- [ ] The report shows the injected fault, the wrong result, each candidate, and before/after
**Verification:** run the command; `uv run pytest tests/test_pipeline.py -q`
**Dependencies:** T5, T6
**Files:** `faultforge/pipeline.py`, `faultforge/cli.py`, `tests/test_pipeline.py`

### Checkpoint B: offline end-to-end (target Oct 6)
- [ ] The full loop runs offline from a clean clone
- [ ] Review with Ramy before moving on

### Phase 2: Live platform (needs credentials)

#### Task 8: Token Factory client and spike — S
**Description:** `TokenFactoryLLM` with two regional clients; a spike script that calls Nano and Ultra and tests JSON output and tool calling. **Blocked on a Nebius API key.**
**Acceptance criteria:**
- [ ] Both regions answer; base URLs and model IDs come from config
- [ ] Findings (JSON mode, tool calling, latency, cost per run) are written to `docs/spikes/token-factory.md`
**Verification:** `uv run python scripts/spike_token_factory.py`
**Dependencies:** T6
**Files:** `faultforge/llm/token_factory.py`, `scripts/spike_token_factory.py`, `docs/spikes/token-factory.md`

#### Task 9: ContreeSandbox and spike — M
**Description:** Contree implementation of the `Sandbox` protocol. **Blocked on Sandboxes beta access.**
**Acceptance criteria:**
- [ ] The example repo gets into a sandbox and its tests run there
- [ ] Two runs from one image `uuid` are isolated from each other
- [ ] How files get in, outbound network and run time limits are written to `docs/spikes/contree.md`
**Verification:** `uv run pytest tests/sandbox -q -m contree`
**Dependencies:** T4
**Files:** `faultforge/sandbox/contree.py`, `tests/sandbox/test_contree.py`, `docs/spikes/contree.md`

#### Task 10: Live repair loop — M
**Description:** Run Task 7's command with Nemotron and Contree; tune prompts until the order-service bug is repaired reliably.
**Acceptance criteria:**
- [ ] 4 of 5 consecutive live runs produce a passing repair
- [ ] A run stays under an agreed token budget
**Verification:** `faultforge run examples/order-service --live` five times
**Dependencies:** T7, T8, T9
**Files:** `faultforge/repair.py`, `faultforge/prompts/*.md`

### Checkpoint C: go / no-go (target Oct 7–9)
- [ ] Live loop works on Nebius; otherwise switch to the Personal AI track

### Phase 3: Scenario generation

#### Task 11: Dependency discovery — M
**Description:** Static scan for `httpx` call sites plus an Ultra pass that names the dependency and the operation at risk.
**Acceptance criteria:**
- [ ] The fulfillment dependency is found in the example repo without hints
- [ ] A repo with no HTTP dependency gets a clear "nothing to test" result
**Verification:** `uv run pytest tests/test_discovery.py -q`
**Dependencies:** T10
**Files:** `faultforge/discovery.py`, `tests/test_discovery.py`

#### Task 12: Scenario generation from templates — M
**Description:** For each fault type, the model fills a template to produce an executable test. A generated test is accepted only if it runs and fails on an assertion, not on an import or syntax error.
**Acceptance criteria:**
- [ ] Four scenarios are generated for the example repo; the duplicate-order one reproduces the bug
- [ ] Tests that error instead of failing are discarded and reported
**Verification:** `uv run pytest tests/test_scenarios.py -q`
**Dependencies:** T11
**Files:** `faultforge/scenarios.py`, `faultforge/prompts/scenario_*.md`, `tests/test_scenarios.py`

#### Task 13: Tavily research — S
**Description:** A runtime Tavily call looks up the dependency's documented timeout, rate-limit and retry behaviour and feeds it into scenario generation, with sources shown.
**Acceptance criteria:**
- [ ] The run makes a real Tavily call and cites the sources it used
- [ ] The pipeline still completes if Tavily fails
**Verification:** `uv run pytest tests/test_research.py -q`; one live run
**Dependencies:** T12
**Files:** `faultforge/research.py`, `tests/test_research.py`

#### Task 14: Two more repos — M
**Description:** A second example (webhook handler, duplicate delivery) and one third-party open-source repo that uses httpx.
**Acceptance criteria:**
- [ ] Both run through the full pipeline
- [ ] The third-party repo's bug is not planted by us
**Verification:** live run on each
**Dependencies:** T12
**Files:** `examples/webhook-service/*`, `examples/README.md`

### Checkpoint D: generation decision (Oct 16)
- [ ] Generation is stable, or scenarios ship as templates

### Phase 4: Product

#### Task 15: API and event stream — M
Start a run, stream its events over SSE, fetch a finished run. **Verify:** `uv run pytest tests/test_api.py -q`. **Depends on:** T7.

#### Task 16: UI — run view and attempt tree — M
Pick a prepared repo, start a run, watch the tree of scenarios and repairs fill in live. **Verify:** manual run in the browser plus a UI smoke test. **Depends on:** T15.

#### Task 17: UI — evidence view — M
Per-scenario before/after, the wrong result, the diff and the regression test for the winning repair. **Depends on:** T16.

#### Task 18: Pull request with evidence — S
Open a PR containing the patch, the regression test and the evidence table. **Depends on:** T10.

#### Task 19: Public demo limits — M
Prepared repos only, per-IP rate limit, caps on turns, run time and concurrency, no secrets inside sandboxes. Gets a security review. **Depends on:** T15.

#### Task 20: Deploy on Nebius Serverless — M
Container + Serverless Endpoint with a public URL. How Serverless bills against the credits is unverified. **Depends on:** T19.

### Checkpoint E: demo-ready (Oct 24)
- [ ] A stranger can open the URL and complete a run

### Phase 5: Submission

#### Task 21: README, architecture diagram, feedback notes — S
#### Task 22: Video under 3 minutes, repo public, Devpost form — S
Submit by Oct 29.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Sandboxes beta access is late or flaky | High | LocalSandbox keeps work moving; go/no-go at Checkpoint C; Docker-on-Serverless as a fallback runner |
| Nemotron writes poor patches or tests | High | Templates, structured output, validation that a test fails for the right reason, N candidates |
| Third-party repo does not fit the httpx constraint | Med | Choose it in week 2; add a `requests` adapter only if nothing fits |
| Demo looks staged | Med | Third-party repo; show failed repair attempts, not only the winner |
| Public endpoint abused | High | Task 19 limits; prepared repos only |
| Serverless costs exceed credits | Med | Verify billing in Task 20 before leaving it running |
| Schedule (Oct 17–23 light) | Med | Checkpoint B fallback exists by Oct 6 |

## Open Questions

1. Licence: MIT assumed. Apache-2.0 instead?
2. UI stack: React + Vite served by FastAPI assumed. Prefer Next.js or something else?
3. When to make the GitHub repo public (it is private now; the rules require public by submission).
4. Where FaultForge opens PRs in the demo: a fork under your account, or a dedicated demo org?
