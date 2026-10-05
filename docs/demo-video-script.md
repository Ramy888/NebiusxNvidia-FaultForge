# Demo video script (under 3 minutes)

Must be public on YouTube, under 3 minutes, show the project working, and explain with audio how
Token Factory and Nemotron are used. No copyrighted music. Record the **live** mode (badge reads
"Live: NVIDIA Nemotron 3 Ultra and Nano on Nebius Token Factory, Token Factory Sandboxes"); keep
one successful run per service recorded in advance, in case a live run doesn't find a repair on
camera.

| Time | Screen | Voice-over |
|---|---|---|
| 0:00–0:15 | Title card → FaultForge home, live badge visible | "Your tests pass. Then a payment provider rate-limits you, and an unpaid order ships. FaultForge finds those failures before production does, and proves the fix." |
| 0:15–0:40 | Pick `order-service` → **Break it and repair it**; the preparation feed fills in | "Nemotron 3 Ultra on Nebius Token Factory reads the service and finds its HTTP dependency. Tavily researches how real providers handle retries. Nemotron writes failure tests, and Ultra reviews each one: real bug, or a mistake in the test?" |
| 0:40–1:05 | Attempt tree: baseline checks turn red; "Reproduced" banner | "Every test runs in Token Factory Sandboxes, each as its own branch of one checkpoint. A timeout after the provider accepted the order: one order, two shipments." |
| 1:05–1:40 | Repair branches appear and settle; one is marked "Proposed fix" | "Ultra plans distinct repairs, Nano writes them, and every failure is replayed against every repair from the same sandbox checkpoint. 'Stop retrying' still fails. The idempotency key passes, and the existing tests still pass." |
| 1:40–2:05 | Evidence panel: before → after, one-line diff, Tavily sources | "The evidence: before and after for every scenario, a one-line patch, the regression test, and the sources Tavily found." |
| 2:05–2:35 | Show hook-slinger: the repo link, then its report | "And on a real open-source project, hook-slinger, unchanged: a duplicate delivery made the receiver process one webhook twice. FaultForge added an idempotency key that survives retries, verified in Sandboxes." |
| 2:35–2:55 | Pull request preview; README | "Then it opens a pull request with the patch, the test and the evidence. Built on Nemotron, Token Factory and Sandboxes; MIT-licensed; link below." |

Record at 1080p; zoom the browser to ~125% so code is legible.
