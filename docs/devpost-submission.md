# Devpost submission draft: FaultForge

**Track:** Coding & Agentic Engineering
**NVIDIA models:** Nemotron 3 Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`), Nemotron 3 Nano (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`)
**Nebius services:** Token Factory (inference), Token Factory Sandboxes
**Also uses:** Tavily (live research on how the real dependency fails)

**Tagline:** Break your service's dependencies on purpose, then get a repair that's proven against the same failures.

---

## Inspiration

Most outages in small backends don't come from the code everyone reads. They come from the code that runs when a dependency misbehaves: a payment provider that rate-limits you, a fulfillment API whose response times out after it already did the work, a webhook delivered twice. Those paths almost never run in tests. Chaos-engineering tools can inject the failure, but a small team still has to work out what broke, write the fix, and prove the fix doesn't break something else. We wanted an agent that does the whole loop.

## What it does

Point FaultForge at a small Python service. It:

1. **Finds the outbound HTTP dependency** (static scan plus Nemotron 3 Ultra naming the dependency and the operation at risk).
2. **Researches how that kind of service really fails** with Tavily: retries, `Retry-After`, idempotency keys.
3. **Writes executable failure tests** for timeouts, rate limits, malformed responses and duplicate delivery. Faults are injected inside the HTTP client, so they are instant and repeatable.
4. **Reviews each reproduced failure** with Ultra: a real application bug, or a mistake in the generated test? Test mistakes go back to the writer with the reason.
5. **Plans distinct repairs** (Ultra) and **writes them** (Nemotron 3 Nano).
6. **Replays every failure against every repair** in Token Factory Sandboxes, each as a branch of one checkpoint. A repair wins only if it fixes a reproduced failure, breaks no existing test and regresses nothing; a failed attempt gets one revision from Ultra, told exactly what verification found.
7. **Proposes a pull request** with the patch, the regression tests and an evidence report.

What it found in live runs:

- **Order service:** a timeout after the provider accepted the order → retry → **one order, two shipments**. Fix found: a one-line `Idempotency-Key` header.
- **Payment webhook service:** a rate-limited charge check (HTTP 429) is read as success → **an unpaid order is marked paid**. Fix found: check the response status.
- **hook-slinger** ([rednafi/hook-slinger](https://github.com/rednafi/hook-slinger), an unchanged open-source project): a duplicate delivery makes **the receiver process the same webhook twice**. Fix found: a stable idempotency key carried through its retry queue.

## How we built it

- **Nemotron 3 Ultra on Token Factory** handles reasoning: dependency analysis, scenario planning, triage, repair strategy, and second attempts with reasoning on.
- **Nemotron 3 Nano on Token Factory** handles fast generation of failure tests and patches, with thinking switched off (it cut runs from ~15 minutes to ~1).
- **Token Factory Sandboxes:** each run of an image yields a new image, so the baseline, every scenario and every repair are parallel branches of one checkpoint. That's the exact shape of "replay every failure against every repair". Model-written code never runs on our machine or the demo server.
- **Tavily** supplies live research on the real dependency, cited in the report.
- **Python, FastAPI and React:** the pipeline, an API with a live event stream, and a UI that shows the attempt tree, preparation feed, and before/after evidence.
- **Engineering discipline:** test-first throughout (180+ tests), a code review that found 15 issues (all fixed), and a two-model security review of the public surface (findings fixed). Live runs are capped per day so a public demo can't drain credit.

## Challenges we ran into

- **Code inside JSON fails for every model size.** Escaping and indentation broke most early patches. Switching to fenced code blocks, with a worked example, fixed it. Super and Ultra as writers did no better than Nano until validation and feedback existed.
- **Generated tests are often wrong in subtle ways.** We learned to tell a broken test from a real bug by where the error is raised: inside the test file means a test bug, inside application code means a real failure. An idea that sounded right, "a valid failure test must pass with the fault switched off", turned out wrong: many correct tests describe what must happen *during* the fault. Live data showed it, so we reverted it.
- **Reading verdicts isn't enough; read the patches.** Some early "repairs" made the app tolerate a mistake in the test. Adding Ultra's triage step fixed that, and we now check every winning diff.
- **Our own fake dependency misled the models.** Its `.accepted` list held request bodies, but tests read IDs from it, and the bug only appeared *after* a correct repair. Adding `.created` and documenting the difference took the order service from 2/4 to 2/2.

## Accomplishments that we're proud of

- **Six genuine repairs in eight live runs** after triage, and every winning patch read and confirmed to change the dependency handling.
- **Fully on Nebius:** Nemotron for every model call, Sandboxes for every execution, about **$0.08 per run**.
- **A real open-source project** repaired without modifying its code.
- Honest evidence: every run shows what broke, what each repair tried, and why it was accepted or rejected.

## What we learned

- Small models write good code when the format is simple (fenced code) and the feedback loop is tight; bigger writers mostly add cost.
- A reasoning model is most valuable as a *reviewer*: triaging failures and revising failed attempts with the concrete error.
- Sandboxes' branching is a natural fit for agents that compare alternatives.

## What's next for FaultForge

- More fault types (partial responses, slow streams, connection resets) and dependencies beyond HTTP (queues, databases).
- A GitHub App that runs FaultForge on pull requests touching dependency code.
- Repairs that keep idempotency keys unique per destination by default (a caveat from the hook-slinger run).

---

## Links (fill in at submission)

- Demo: https://realramy-faultforge.static.hf.space/ — recorded live runs. Hugging Face only hosts
  the static page: it makes no model calls, and no NVIDIA model is called through Hugging Face. All
  Nemotron calls go to Nebius Token Factory; all code runs in Token Factory Sandboxes.
- Video: _YouTube URL_
- Code: https://github.com/Ramy888/NebiusxNvidia-FaultForge (MIT; must be public at submission)
