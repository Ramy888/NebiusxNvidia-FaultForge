# Live runs on Nemotron (2026-10-04)

Every run below used NVIDIA Nemotron 3 Ultra (planning, analysis, second attempts) and Nemotron 3
Nano (writing tests and patches) on Nebius Token Factory, plus a live Tavily search, on the two
example services. Runs used the local sandbox inside a Docker container (Token Factory Sandboxes
access pending). "Repaired" means a patch passed: every existing test, no regressions, and at
least one reproduced failure fixed.

| Iteration | Change | Repaired |
|---|---|---|
| 1 | first live run | 0 / 1 |
| 2 | — (diagnostics added) | 0 / 1 |
| 3 | code normalisation; Super as writer compared | 0 / 2 |
| 4 | code as fenced blocks, worked example, no writer thinking | 1 / 1, then 0 / 3 |
| 5 | repairs see all failures; one revision; "count effects, not requests" | 3 / 5 |
| 6 | fault-off control run (later reverted) | 3 / 8, Super 2 / 4, Ultra 2 / 4 |
| 7 | traceback check for test bugs instead of the control run | 5 / 8 (webhook 4 / 4) |
| 8 | second attempts escalate to Ultra with reasoning | 5 / 8 reported, **3–4 / 8 genuine** (order 2 / 4, webhook 1–2 / 4) |

| 9 | triage each reproduced failure: application bug or test mistake | **6 / 8, all genuine** (order 2 / 4, webhook 4 / 4) |

| 10 | fault kit: `FakeAPI.created` (objects with ids) vs `.accepted` (request bodies) | order service **2 / 2** |

**First run fully on Token Factory Sandboxes (2026-10-05):** order service repaired with the
idempotency key; every scenario, baseline and repair ran as a branch of one sandbox checkpoint.
2 min 48 s end to end, about $0.08 of Nemotron, Sandboxes free during beta.

**Third-party repo, hook-slinger, on Sandboxes (2026-10-05):** repaired in 3 min 18 s (~$0.12).
The duplicate-delivery scenario reproduced (2 deliveries processed); the first repair failed, Ultra's
revision passed: a stable `Idempotency-Key` on every delivery, carried through rq retries. Caveat a
reviewer should raise: the key hashes only the payload, so identical payloads to different
receivers would share a key. The upstream "non-200 counts as failure" bug was noticed in the test
but not kept as a scenario in this run.

**Known weakness (2026-10-06):** in one of two webhook runs on Sandboxes the winning patch, besides
a real fix, made `OrderBook.status` return "unknown" for missing orders, which papers over a
generated test that never created its order. Triage does not always catch that. The published
recording uses the other run, whose patch only touches the payment check.

**Fixed (2026-10-09): repairs must stay on the dependency path.** `faultforge/scope.py` rejects a
repair that changes an existing function the dependency path never reaches (the operation at risk,
the call sites, and every repo function they reference). That exact patch is now rejected
("changes code off the dependency path (payments/webhooks.py:OrderBook.status)"), so the next
candidate can win or the rejected one is revised with that reason. All four genuine live winners
on record (the three recordings and the hosted run of 2026-10-09) still pass; tests in
`tests/test_scope.py`. It makes no model call, so it adds no cost.

**Re-triage after repair (2026-10-09).** The guard also gives evidence about the tests. If a
reproduced failure was made to pass only by patches that changed nothing on the dependency path,
the test most likely relies on something the app never promised. That test goes back to the
writer with the off-path functions, the patches and its original failure; the corrected test is
validated and triaged again, and the run is repeated once (no further re-triage). If a patch that
made it pass also changed the path, the real fix may be what made it pass, so the test is only
reported as possibly mistaken. Verified by tests (`tests/test_retriage.py`); it cannot be forced
in a live run, since a mistaken generated test cannot be produced on demand.

Iteration 10's cause: every failed order-service run had the correct idempotency repair, undone by
a generated test reading `["id"]` from `.accepted` (request bodies). The test bug only appeared
after the repair, so validation could not see it; fixing the fault kit's API and docs did.

Iteration 9's winners were all read: every one changes the dependency path (`Idempotency-Key`
header; `raise_for_status()` / `if not response.is_success` in the payment verifier). Triage
flagged 16 generated tests as test mistakes across the 8 runs and sent them back to the writer.

**Reading the winning patches changed the numbers.** Some "repairs" fixed a mistake in the
generated test rather than the app: the test never created the order it then looked up
(`KeyError: 'order_456'`), and the winning patch made `OrderBook.status` return `"unknown"` for
missing orders. These pass verification but are not fixes (iteration 7: d1; iteration 8: f1).
Genuine winners change the dependency path: an `Idempotency-Key` header on the order service,
`raise_for_status()` / explicit status checks in the payment verifier. Open fix: before planning
repairs, have the reasoning model triage each reproduced failure as "application bug" or "test
mistake".

What each lesson was:

- **Code inside JSON strings fails for every model size.** Asking for fenced code blocks fixed most
  syntax and escaping errors (iteration 4).
- **Nano's default reasoning cost minutes per call** for little gain when writing code; turning it
  off cut a run from ~15 minutes to ~1 minute.
- **Bigger writers did not help on their own** (Super and Ultra scored like Nano in iteration 6):
  the bottleneck was validation and feedback, not model size.
- **A generated test is broken when it raises a non-assertion error in its own code**; the same
  error inside application code is a real failure. A "must pass without the fault" check sounded
  right but rejected valid fault-conditional tests.
- **Second attempts work best with the reasoning model**, told why the first attempt failed.

With triage, a run now costs about $0.08 (most of it Ultra). Typical token use per run before triage: ~3–4k prompt / ~4–5k completion tokens on Ultra for planning, ~6k / ~1k
on Nano for writing, plus up to ~17k completion tokens on Ultra when a second attempt is needed.

**Triage inverted the flagship test (2026-10-17):** on the hosted demo, triage called the order-service
timeout test a mistake ("the retry inevitably creates a second"); the rewrite asserted the duplicates,
passed on the buggy code and then rejected the correct Idempotency-Key repair, so the run ended with
no verified repair. Fixes: a rewrite of a triage-flagged test that passes on the original code is
dropped, and the triage prompt now says the test states what *should* happen, so a retry that
creates a second order is the bug. Next live CLI run on Sandboxes: the timeout test kept,
Idempotency-Key repair accepted (timeout and duplicate delivery both failed → passed).
