# Live demo on Cloudflare Containers

A Worker in front of one container running the FaultForge server in **live** mode: Nemotron 3
Ultra and Nano on Nebius Token Factory, every test and repair in Token Factory Sandboxes, Tavily
research. Model-written code never runs in the container (live mode refuses any other sandbox).

What the Worker adds:
- **Credit caps that survive restarts.** Live runs are capped per UTC day (`LIVE_RUNS_PER_DAY`,
  8) and in total (`LIVE_RUNS_TOTAL`, 250) in Durable Object storage. The server's own daily count
  lives in memory and resets when the container sleeps. The scripted run is never capped.
- **Per-visitor rate limits.** It replaces `X-Forwarded-For` with Cloudflare's `CF-Connecting-IP`,
  and the server trusts it (`FAULTFORGE_TRUST_PROXY=1`).
- **HTTPS only.**

Needs the Workers Paid plan (Containers). The instance (`basic`, 1/4 vCPU, 1 GiB) sleeps after
15 idle minutes.

```bash
cd deploy/cloudflare
npm install
npm test && npm run check
npx wrangler deploy
# secrets, once (values from the repo's .env; never commit them)
npx wrangler secret put NEBIUS_API_KEY
npx wrangler secret put NEBIUS_PROJECT_ID
npx wrangler secret put TAVILY_API_KEY
```
