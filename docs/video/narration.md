# Voice-over for `faultforge-demo-silent.mp4`

The video is 2:39, 1920×1080, with no sound. It shows the public demo page replaying three real live
runs (no model calls during the recording). Read each line when the clock reaches its time. Every
line fits its gap at a calm pace; if you finish early, pause, the screen keeps moving.

Devpost needs audio that explains how Nemotron and Token Factory are used. The lines at 0:06, 0:12
and 0:38 cover that. Ways to add your voice:
- **iMovie:** drop in the video, then use Record Voiceover.
- **QuickTime:** record the audio, then merge it in iMovie or CapCut.
- **CapCut:** import the video, then use Record.

| Time | On screen | Say |
|---|---|---|
| 0:00 | Home page | "Your tests pass. Then a dependency misbehaves, and production breaks." |
| 0:06 | "About this page" notice | "These are recorded live runs: Nemotron on Nebius Token Factory, tests in Token Factory Sandboxes." |
| 0:12 | order-service, preparation feed fills in | "A shop backend. Nemotron 3 Ultra reads the code and finds its HTTP dependency, the fulfillment provider. Tavily researches how real providers fail. Nemotron writes failure tests for timeouts, rate limits and malformed responses, and Ultra reviews each one: a real bug, or a mistake in the test? Broken tests go back to be fixed." |
| 0:38 | "Reproduced" banner, then the attempt tree | "Reproduced: a timeout after the provider accepted the order, so the retry ships it twice. Ultra plans competing repairs, Nano writes them, each in its own sandbox branch." |
| 0:48 | Evidence: what broke, before → after | "Every failure is replayed against every repair. The winner fixes it, regresses nothing, and keeps the existing tests green." |
| 0:56 | Patch | "The patch: an idempotency key with the order ID." |
| 1:00 | Tavily sources | "Grounded in research, with sources." |
| 1:07 | webhook-service runs | "Second service: a payment webhook that asks the provider whether a charge succeeded before marking the order paid. Same loop: find the dependency, research it, write and check the failure tests, and run everything in Sandboxes. Some repairs fail verification here, and the tree shows exactly why they were rejected." |
| 1:37 | "Reproduced" banner | "A rate-limited check, HTTP 429, is read as success: an unpaid order is marked paid." |
| 1:43 | Patch | "The fix checks the response status first." |
| 1:50 | hook-slinger runs | "Finally, a real open-source project, hook-slinger, unchanged. Nemotron finds its webhook delivery path, writes a duplicate-delivery test, and confirms it reproduces." |
| 2:17 | "Reproduced" banner | "A duplicate delivery is processed twice." |
| 2:23 | Patch, sources | "The repair carries a stable idempotency key through the retry queue. FaultForge then opens a pull request with the patch, the test and the evidence." |
| 2:34 | Home page | "FaultForge: NVIDIA Nemotron on Nebius Token Factory, about eight cents a run." |

## Re-recording

`scripts/demo-video/record.mjs` drives headless Chrome over the replay build and writes the frames; it
prints the `ffmpeg` command that makes the MP4. The header of that file says how to serve the build.
