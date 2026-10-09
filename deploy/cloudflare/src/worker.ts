// Hosted live FaultForge demo on Cloudflare Containers: this Worker, then one container running
// the FaultForge server in live mode (Nemotron on Token Factory, every check in Token Factory
// Sandboxes). Model-written code never runs in the container; the server refuses live mode
// without Sandboxes.
import { Container, getContainer } from "@cloudflare/containers";
import { type Caps, release, remaining, reserve } from "./budget";
import { decodedPath, isRunStart } from "./routes";

interface Env {
  FAULTFORGE: DurableObjectNamespace<FaultForge>;
  NEBIUS_API_KEY?: string;
  NEBIUS_PROJECT_ID?: string;
  TAVILY_API_KEY?: string;
  LIVE_RUNS_PER_DAY?: string;
  LIVE_RUNS_TOTAL?: string;
}

const caps = (env: Env): Caps => ({
  perDay: Number(env.LIVE_RUNS_PER_DAY ?? 8),
  total: Number(env.LIVE_RUNS_TOTAL ?? 250),
});

const json = (body: unknown, status = 200, headers: HeadersInit = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

export class FaultForge extends Container<Env> {
  defaultPort = 8000;
  sleepAfter = "15m"; // a run takes 2-3 minutes; its event stream keeps the container awake
  enableInternet = true; // Token Factory, Token Factory Sandboxes and Tavily

  constructor(ctx: DurableObjectState<{}>, env: Env) {
    super(ctx, env);
    this.envVars = {
      FAULTFORGE_MODE: "live",
      FAULTFORGE_SANDBOX: "contree",
      // the Worker sets X-Forwarded-For to the visitor's address, so per-visitor limits work
      FAULTFORGE_TRUST_PROXY: "1",
      FAULTFORGE_LIVE_RUNS_PER_DAY: String(caps(env).perDay),
      NEBIUS_API_KEY: env.NEBIUS_API_KEY ?? "",
      NEBIUS_PROJECT_ID: env.NEBIUS_PROJECT_ID ?? "",
      TAVILY_API_KEY: env.TAVILY_API_KEY ?? "",
    };
  }

  override async fetch(req: Request): Promise<Response> {
    const path = decodedPath(new URL(req.url).pathname);
    if (path === null) return json({ detail: "malformed path" }, 400);
    const store = this.ctx.storage;
    const now = new Date();

    if (isRunStart(req.method, path)) {
      const body = (await req.clone().json().catch(() => ({}))) as { mode?: string };
      if (body.mode === "demo") return super.fetch(req); // the scripted run calls no model
      if (!(await reserve(store, caps(this.env), now))) {
        return json({ detail: "the daily live-run budget is used up; try the scripted run instead" }, 429);
      }
      try {
        const res = await super.fetch(req);
        if (res.status !== 202 && res.status !== 200) await release(store, now);
        return res;
      } catch (error) {
        await release(store, now);
        throw error;
      }
    }

    if (req.method === "GET" && path === "/api/info") {
      const res = await super.fetch(req);
      if (!res.ok) return res;
      const info = (await res.json()) as { mode?: string; live_runs_left_today?: number };
      if (info.mode === "live") info.live_runs_left_today = await remaining(store, caps(this.env), now);
      return json(info);
    }

    return super.fetch(req);
  }
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (url.protocol === "http:" && url.hostname !== "localhost") {
      url.protocol = "https:";
      return Response.redirect(url.toString(), 301);
    }
    // One instance: runs and their event streams live in the server's memory.
    // Replace any client-supplied X-Forwarded-For with the address Cloudflare saw.
    const headers = new Headers(req.headers);
    headers.set("X-Forwarded-For", req.headers.get("CF-Connecting-IP") ?? "unknown");
    return getContainer(env.FAULTFORGE, "live").fetch(new Request(req, { headers }));
  },
};
