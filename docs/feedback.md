# Feedback on Nebius and NVIDIA tools

_From building FaultForge, 2 to 5 October 2026: about 55 live runs on Token Factory, Token Factory
Sandboxes, NVIDIA Nemotron 3 Ultra / Super / Nano and Tavily. Ramy, review this before pasting it
into the Devpost feedback section; every point below comes from something that happened during the
build._

## What worked well

- **Sandboxes' branching model fits agents perfectly.** "Every run yields a new image" made
  FaultForge's core loop trivial: one checkpoint, then the baseline, every failure scenario and
  every candidate repair run as parallel branches of it.
- **Fast, friendly Sandboxes onboarding.** We requested beta access through the console form on
  Oct 4 and it was active on Oct 5, with a clear welcome email and a working example. Using the
  same API key and project ID as inference meant no new credentials.
- **Nemotron 3 Ultra is a strong planner and reviewer.** Its repair strategies were sensible
  (idempotency keys, safe retries, explicit status checks), and as a reviewer it reliably told
  genuine application bugs from mistakes in generated tests.
- **JSON mode and tool calling work on both Ultra and Nano**, and Ultra returns its reasoning in
  a separate field, so `content` stays clean and parseable.
- **Cost is low:** a full FaultForge run (discover, research, write tests, triage, repair, verify)
  costs about $0.08.

## Friction, with suggestions

### Token Factory inference
1. **Model endpoints are region-scoped, but the docs show one base URL.** Nano and Lightning are
   served from eu-north1 and Super/Ultra from us-central1. The function-calling and JSON pages only
   show `api.tokenfactory.nebius.com/v1`, so routing between Nano and Ultra silently needs two
   clients. *Suggestion: a model → base URL table in the docs and the model catalog.*
2. **No capability matrix.** The catalog lists Nemotron models as `text2text` but not which support
   tool calling, JSON mode or a reasoning switch; the function-calling page's only example uses a
   Llama model. We had to probe each one.
3. **Nemotron Nano reasons by default, and turning that off is undocumented.** For code writing,
   the hidden reasoning cost thousands of tokens and minutes per call. Passing
   `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` worked (17 vs 83 completion
   tokens on a trivial prompt; whole runs went from ~15 minutes to ~1). *Suggestion: document the
   switch per model.*
4. **Ultra's reasoning can use up `max_tokens` and leave `content` empty.** One planning call came
   back with no answer until we raised the limit. *Suggestion: document that reasoning counts
   against `max_tokens`, and make `finish_reason` obvious in examples.*

### Token Factory Sandboxes
5. **The SDK does more than the getting-started page shows.** File upload (`run(files=...)`,
   `apply_files`), `disposable=False` (needed to branch from a result) and the fact that a `str`
   value in `files` is a *local path* while `bytes` is content were only discoverable from the SDK
   source.
6. **`apply_files()` returns an image that is already finished, and calling `.wait()` on it raises
   `ContreeImageStateError`** ("cannot have state SUCCEEDED"). `.wait()` is required after `run()`,
   so the asymmetry is surprising. *Suggestion: make `wait()` a no-op on finished images, or
   document it.*
7. **Two names for the project ID.** The CLI tutorial uses `NEBIUS_AI_PROJECT`; the SDK and the
   welcome email use `NEBIUS_PROJECT_ID`.
8. **Pricing after the beta, preloaded base images and run limits are not documented.** The
   50-concurrent-operations cap is, which helped us size our parallel replay.

### Nebius AI Cloud
9. **It is not clear whether hackathon credit covers hosting.** The rules encourage Serverless
   endpoints, but AI Cloud billing is separate from Token Factory credit and asks for a card and a
   $25 top-up. *Suggestion: say plainly on the Resources page what the hackathon credit covers.*

### Building with LLM-generated code (lessons that may help other entrants)
10. **Asking any model size for code inside JSON strings fails often** (escaping, indentation).
    Fenced code blocks fixed most of it. Super and Ultra as writers did no better than Nano until
    validation and feedback were added. That's worth a note in the Nemotron cookbook.

## Hackathon materials

11. The rules list NemoClaw, OpenShell and Hermes Agent next to models. Saying which are models
    and which are runtimes would help entrants choose a track.
