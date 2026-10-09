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
4. **Reviews each reproduced failure** with Ultra: a real application bug, or a mistake in the generated test? Test mistakes go back to the writer with the reason. Tests are checked again after repair: if only patches that changed code off the dependency path could make a test pass, it goes back to the writer and the run is repeated once with the corrected test.
5. **Plans distinct repairs** (Ultra) and **writes them** (Nemotron 3 Nano).
6. **Replays every failure against every repair** in Token Factory Sandboxes, each as a branch of one checkpoint. A repair wins only if it fixes a reproduced failure, breaks no existing test, regresses nothing and changes no existing code off the dependency path (so a patch that only bends the app to fit a mistaken test loses, even with every check green); a failed attempt gets one revision from Ultra, told exactly what verification found.
7. **Proposes a pull request** with the patch, the regression tests and an evidence report.

What it found in live runs:

- **Order service:** a timeout after the provider accepted the order → retry → **one order, two shipments**. Fix found: a one-line `Idempotency-Key` header.
- **Payment webhook service:** a rate-limited charge check (HTTP 429) is read as success → **an unpaid order is marked paid**. Fix found: check the response status.
- **hook-slinger** ([rednafi/hook-slinger](https://github.com/rednafi/hook-slinger), an unchanged open-source project): a duplicate delivery makes **the receiver process the same webhook twice**. Fix found: a stable idempotency key carried through its retry queue.

## How we built it

- **Nemotron 3 Ultra on Token Factory** handles reasoning: dependency analysis, scenario planning, triage, repair strategy, and second attempts with reasoning on.
- **Nemotron 3 Nano on Token Factory** handles fast generation of failure tests and patches, with thinking switched off (it cut runs from ~15 minutes to ~1).
- **Token Factory Sandboxes:** each run of an image yields a new image, so the baseline, every scenario and every repair are parallel branches of one checkpoint. That's the exact shape of "replay every failure against every repair". Model-written code never runs on our machine or the demo server.
- **Tavily** grounds the failure tests in how real services behave. Once Ultra has named the dependency, FaultForge runs one Tavily search on how that kind of API handles timeouts, rate limits, `Retry-After`, retries and idempotency keys. It passes Tavily's answer and the top five sources to the test writer as research notes. These notes are why the tests assert what the app *promised*, such as "one order is one shipment" or "a 429 is not a payment", rather than counting HTTP calls. Each live run surfaced the conventions the eventual fix followed: Stripe, Shopify and Adyen's idempotency-key docs for the order and payment services, and webhook-retry guides for hook-slinger. Every source is listed with its link in the run's preparation feed and in the evidence report. If Tavily is unavailable, the run continues without the notes, and the preparation feed shows that the research was skipped.
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

## Feedback on Nebius Token Factory and NVIDIA Nemotron

From about 40 live runs over a week; see [`docs/live-runs.md`](docs/live-runs.md) for the details.

**What worked well**

- **Sandboxes' image-per-run model is the best primitive we used.** Every run returns a new image, so "baseline plus N scenarios times M repairs" is just several runs from one checkpoint, with no snapshot API to learn. Other agent builders comparing alternatives should hear about this.
- **Price per useful result.** A full reproduce, repair and replay run costs about $0.08, mostly Ultra. Nano at $0.24/M output is cheap enough to retry freely.
- **OpenAI compatibility held.** JSON mode and tool calling worked on Nemotron 3 Ultra and Nano with the stock `openai` client.

**What cost us time, and what would fix it**

1. **Models live in different regions behind different base URLs.** Nano is in eu-north1 and Ultra in us-central1, so a planner–writer setup needs two clients. The starter code assumes one base URL. *Suggestion:* show the base URL next to each model in the catalog, or route any model from one global endpoint.
2. **Nano's default reasoning is very slow for code writing.** With thinking on, a run took about 15 minutes. With it off, it took about 1 minute, with no loss in patch quality for our use. *Suggestion:* document how to turn thinking off for each model, and say where it is worth the time.
3. **Code inside JSON breaks for every Nemotron size.** Escaping and indentation broke most patches returned as JSON strings, and fenced code blocks fixed it. *Suggestion:* a cookbook note on getting code output from Nemotron would save other teams the same days.
4. **Sandboxes beta access was unclear from the API side.** Before enablement every call returned a 403 that didn't say beta access was pending. Access went through a separate form. *Suggestion:* return an error that names the beta and links the form.
5. **Undocumented Sandboxes behaviour we had to find by trial:**
   - `apply_files()` returns an image that is already `SUCCEEDED`, and calling `wait()` on it raises an error.
   - Whether outbound network works was not documented. It does, and we needed it for `pip install`.
   - Run time limits and localhost/multi-process behaviour were not documented either.

   *Suggestion:* one "behaviour and limits" page.
6. **The function-calling docs show only a Llama example.** We had to test Nemotron tool calling ourselves before relying on it. *Suggestion:* show a Nemotron example, since it is the featured model family.

---

## Links (fill in at submission)

- Live demo: https://faultforge-demo.ramy-comm.workers.dev/ (Cloudflare hosts only the web server; every model call goes to Token Factory)
- Replay: https://realramy-faultforge.static.hf.space/ — recorded live runs. Hugging Face only hosts
  the static page: it makes no model calls, and no NVIDIA model is called through Hugging Face. All
  Nemotron calls go to Nebius Token Factory; all code runs in Token Factory Sandboxes.
- Video: https://youtu.be/zSOExa4RrCc
- Code: https://github.com/Ramy888/NebiusxNvidia-FaultForge (MIT; must be public at submission)
