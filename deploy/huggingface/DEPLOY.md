# Deploying the demo as a Hugging Face Docker Space (free hosting)

Fallback if Nebius AI Cloud hosting is not covered by hackathon credit. Hosting is free; live runs
still call Token Factory (about $0.08 each), capped by `FAULTFORGE_LIVE_RUNS_PER_DAY`.

## One-time (Ramy)

1. Create a Space at huggingface.co → New Space → SDK **Docker**, visibility **Public**.
2. In the Space's **Settings → Variables and secrets**, add:

   | Kind | Name | Value |
   |---|---|---|
   | Secret | `NEBIUS_API_KEY` | Token Factory API key |
   | Secret | `NEBIUS_PROJECT_ID` | Token Factory project ID |
   | Secret | `TAVILY_API_KEY` | Tavily key |
   | Variable | `FAULTFORGE_MODE` | `live` |
   | Variable | `FAULTFORGE_SANDBOX` | `contree` (model-written code runs in Sandboxes, not on the Space) |
   | Variable | `FAULTFORGE_TRUST_PROXY` | `1` (the Space sits behind Hugging Face's proxy) |
   | Variable | `FAULTFORGE_LIVE_RUNS_PER_DAY` | `40` |

## Each release

```bash
scripts/make_hf_space.sh /tmp/faultforge-space   # builds the Space folder from the current commit
cd /tmp/faultforge-space
git init -q && git remote add space https://huggingface.co/spaces/<user>/faultforge
git add -A && git commit -qm "Release" && git push -f space HEAD:main
```

The Space rebuilds the Dockerfile automatically; the URL is
`https://<user>-faultforge.hf.space`.
