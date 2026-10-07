# Voice-over for `faultforge-demo-silent.mp4`

The video is 2:56, 1920×1080, with no sound. Until 2:34 it shows the public demo page replaying three real live
runs (no model calls during the recording); from 2:34 to 2:51 it shows a real live run recorded on 8 October 2026
(order-service, Nemotron on Token Factory, Token Factory Sandboxes, repaired in about two minutes), sped up 20× in
the middle. The narrated version is `faultforge-demo-voiceover.mp4`, made from `narration-en.json` in Ramy's cloned
voice (Cartesia Sonic 3.6). Read each line when the clock reaches its time. Every
line fits its gap at a calm pace; if you finish early, pause, the screen keeps moving.

Devpost needs audio that explains how Nemotron and Token Factory are used. The lines at 0:06, 0:12
and 0:38 cover that. Ways to add your voice:
- **iMovie:** drop in the video, then use Record Voiceover.
- **QuickTime:** record the audio, then merge it in iMovie or CapCut.
- **CapCut:** import the video, then use Record.

| Time | On screen | Say |
|---|---|---|
| 0:00 | Home page | "Your tests pass. Then a dependency misbehaves, and production breaks." |
| 0:06 | "About this page" notice | "Recorded live runs: Nemotron on Nebius Token Factory, tests in Sandboxes." |
| 0:12 | order-service, preparation feed fills in | "A shop backend. Nemotron 3 Ultra reads the code and finds its HTTP dependency, the fulfillment provider. Tavily researches how real providers fail. Nemotron writes failure tests for timeouts, rate limits and malformed responses, and Ultra reviews each one: a real bug, or a mistake in the test? Broken tests go back to be fixed." |
| 0:38 | "Reproduced" banner, then the attempt tree | "Reproduced: the retry after a timeout ships the order twice. Ultra plans repairs, Nano writes them, each in its own sandbox." |
| 0:48 | Evidence: what broke, before → after | "Every failure is replayed against every repair. The winner fixes it without breaking any test." |
| 0:56 | Patch | "The fix: an idempotency key per order." |
| 1:00 | Tavily sources | "Grounded in Tavily research on real providers, with sources." |
| 1:07 | webhook-service runs | "Second service: a payment webhook that asks the provider whether a charge succeeded before marking the order paid. Same loop: find the dependency, research it, write and check the failure tests, and run everything in Sandboxes. Some repairs fail verification here, and the tree shows exactly why they were rejected." |
| 1:37 | "Reproduced" banner | "A rate limit response is read as success: an unpaid order is marked paid." |
| 1:43 | Patch | "The fix checks the response status first." |
| 1:50 | hook-slinger runs | "Finally, a real open-source project, hook-slinger, unchanged. Nemotron finds its webhook delivery path, writes a duplicate-delivery test, and confirms it reproduces." |
| 2:17 | "Reproduced" banner | "A duplicate delivery is processed twice." |
| 2:23 | Patch, sources | "The repair derives an idempotency key from the payload. FaultForge then opens a pull request with the patch, the test and the evidence." |
| 2:34 | Live run (local server in live mode, 20× speed in the middle, badge on screen) | "And this is a live run, sped up twenty times: Nemotron on Token Factory, every check in Token Factory Sandboxes. About two minutes from a fresh start to a verified repair." |
| 2:51 | Home page | "FaultForge. Nemotron on Token Factory. About eight cents a run." |

## Re-recording

`scripts/demo-video/record-live.mjs` records the live segment against a local server in live mode (it spends
credit, about $0.08 a run); its header gives the server command. The clip
keeps 2.5-7.0 s and 137.5-143.9 s of that recording at real time and plays 7.0-136.5 s at 20×, with a badge
saying which; it is spliced into the silent video at 2:34, before the closing home-page beat.

`scripts/demo-video/record.mjs` drives headless Chrome over the replay build and writes the frames; it
prints the `ffmpeg` command that makes the MP4. The header of that file says how to serve the build.
