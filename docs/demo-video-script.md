# Demo video script (under 3 minutes) — DRAFT

Must be public on YouTube, under 3 minutes, show the project working, and explain with audio how
Token Factory and Nemotron are used. No copyrighted music.

| Time | Screen | Voice-over |
|---|---|---|
| 0:00–0:15 | Title card → FaultForge home page | "Your tests pass. Then a payment provider rate-limits you, and an unpaid order ships. FaultForge finds those failures before production does — and proves the fix." |
| 0:15–0:35 | Pick `order-service`, press **Break it and repair it** | "This shop retries fulfillment requests that time out. Its own tests pass. FaultForge finds the HTTP dependency and asks Nemotron 3 Ultra on Nebius Token Factory which operation is at risk." |
| 0:35–1:05 | Attempt tree fills in; red "Reproduced" banner | "It injects a timeout *after* the provider accepted the order — deterministic, inside the HTTP client. Every check runs in its own Token Factory Sandbox branch. Result: one order, two shipments." |
| 1:05–1:40 | Repair branches appear and settle | "Ultra plans distinct repairs; Nemotron 3 Nano writes each one. FaultForge replays every failure against every repair from the same sandbox checkpoint. 'Stop retrying' still fails. The idempotency key passes — and the existing tests still pass." |
| 1:40–2:10 | Evidence panel: before → after, diff, regression test, Tavily sources | "The evidence: before and after for every scenario, a one-line patch, a regression test, and sources Tavily found on how the real provider handles retries." |
| 2:10–2:35 | Run `webhook-service` | "Second service: a 429 during the payment check is read as success. FaultForge catches it and ranks two verified repairs." |
| 2:35–2:55 | Pull request preview; README | "Then it opens a pull request with the patch, the test and the evidence. Built on Nemotron and Token Factory; MIT-licensed; link below." |

Record at 1080p; zoom the browser to ~125% so code is legible.
