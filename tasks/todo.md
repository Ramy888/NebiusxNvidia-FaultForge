# FaultForge — task list

Details and acceptance criteria: [plan.md](plan.md). Deadline Oct 30, 19:00 Cairo.

## Needs Ramy (blocks Phase 2)
- [ ] Nebius account → Token Factory API key + project ID
- [ ] Claim credits: promo code `NEBIUS-DEVPOST-GLOBAL26` + Builders Program
- [x] Request Sandboxes beta access (submitted 2026-10-04; credentials verified, awaiting enablement)
- [x] Tavily API key (free plan; in .env)

## Phase 0 — Foundation (offline)
- [x] T1 Project scaffold and gates
- [x] T2 Example order service with the planted bug
- [x] T3 Faultkit + hand-written failing scenario
- [x] **Checkpoint A** — bug reproduced deterministically

## Phase 1 — Repair and replay (offline fallback)
- [x] T4 Sandbox protocol + LocalSandbox
- [x] T5 Replay matrix and scoring
- [x] T6 LLM protocol, stub, repair generation
- [x] T7 CLI end-to-end on the example repo
- [x] **Checkpoint B** — offline end-to-end (target Oct 6)

## Phase 2 — Live platform
- [x] T8 Token Factory client + spike (verified live 2026-10-04)
- [x] T9 ContreeSandbox + spike (verified live 2026-10-05)
- [x] T10 Live repair loop — live on Nemotron + Token Factory Sandboxes (2026-10-05)
- [ ] **Checkpoint C** — go / no-go on the track (Oct 7–9): needs credentials

## Phase 3 — Scenario generation
- [x] T11 Dependency discovery
- [x] T12 Scenario generation from templates
- [x] T13 Tavily research (live call verified 2026-10-03: 5 sources incl. Stripe, Shopify docs)
- [x] T14 Two more repos — webhook-service + hook-slinger (third-party, live on Sandboxes 2026-10-05)
- [~] **Checkpoint D** — template-based generation built; stability needs live Nemotron runs (Oct 16)

## Phase 4 — Product
- [x] T15 API and event stream
- [x] T16 UI: run view and attempt tree
- [x] T17 UI: evidence view
- [x] T18 Pull request with evidence
- [x] T19 Public demo limits — debate-review done 2026-10-04 (P0 + P2 fixed)
- [x] T20 Deploy — static replay of recorded live runs at realramy-faultforge.static.hf.space (2026-10-06); live hosting still blocked on billing
- [ ] **Checkpoint E** — demo-ready (Oct 24): offline demo ready; live demo not yet

## Phase 5 — Submission
- [x] T21 README (with architecture diagram), feedback draft, video script draft
- [~] T22 Video, repo public, Devpost form — Devpost draft in docs/devpost-submission.md; video, public repo and submission left for Ramy (by Oct 29)

## After submission (hardening)
- [x] Scope guard: reject repairs that change code off the dependency path (2026-10-09, `faultforge/scope.py`)
- [ ] Re-triage: when every candidate that fixed scenario X was rejected as off-path, X is probably a test mistake; send it back to the writer instead of reporting no repair
