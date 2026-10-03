# Feedback on Nebius and NVIDIA tools — DRAFT

_Draft from what was observed while building FaultForge (2026-10-02/03). Ramy: edit, add your own
experience from the live runs, and paste into the Devpost feedback section. A "Most Valuable
Feedback" prize ($100 + swag × 10) is awarded on this section._

## Token Factory (inference)

- **Region-scoped model endpoints are easy to miss.** Nano/Lightning are in eu-north1 and
  Super/Ultra in us-central1, but the function-calling and JSON docs only show
  `api.tokenfactory.nebius.com/v1`. A table of model → base URL in the docs would save time; an
  app that routes between Nano and Ultra needs two clients.
- **Capability matrix missing.** The model catalog lists Nemotron models as `text2text` but does
  not say which support tool calling, JSON mode or a reasoning toggle. The function-calling page's
  only example uses a Llama model.
- _(after live runs)_ Where reasoning is returned (`<think>` in `content` vs a separate field),
  latency, and cost per FaultForge run.

## Token Factory Sandboxes (Contree)

- **The branching model is a great fit for agents.** "Every run yields a new image" made
  "replay N failures × M repairs from one checkpoint" trivial to express.
- **SDK docs are thinner than the SDK.** The getting-started page shows only `images.use` and
  `run(shell=...)`. Uploading files (`run(files=...)`, `apply_files`), `disposable=False` (needed
  to branch from a result) and the fact that a `str` value in `files` is a *local path* while
  `bytes` is content were only discoverable by reading the SDK source.
- **Pricing/limits:** no page states Sandboxes pricing or which base images are preloaded; the
  50-concurrent-operations beta cap is documented, which helped size the replay pool.
- _(after live runs)_ How beta access was granted, outbound network defaults, per-run latency.

## NVIDIA Nemotron

- _(after live runs)_ Quality of Ultra's repair strategies vs Nano's patches; JSON adherence;
  failures seen.

## Hackathon materials

- The rules page lists NemoClaw / OpenShell / Hermes Agent alongside models; clarifying which
  are models and which are runtimes would help entrants choose a track.
