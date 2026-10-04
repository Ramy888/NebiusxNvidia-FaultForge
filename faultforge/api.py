"""HTTP API: start a run on a prepared example, follow it live, fetch the evidence."""

import asyncio
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auto import auto_scenarios
from .demo import DESCRIPTIONS, EXAMPLES
from .events import EventLog
from .limits import RateLimiter
from .pipeline import load_stub, run_pipeline
from .pr import PullRequestError, open_pull_request, plan_pull_request
from .sandbox import LocalSandbox, SandboxError, ensure_isolated_for_live
from .scenarios import scenario_from_file
from .serialize import result_to_dict

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


class _PageFiles(StaticFiles):
    """Serve the UI; the HTML page is revalidated on every load so a new release is picked up.
    Bundled assets have content hashes in their names, so they may be cached normally."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.media_type == "text/html":
            response.headers["Cache-Control"] = "no-cache"
        return response


class RunRequest(BaseModel):
    example: str


@dataclass
class Run:
    id: str
    example: str
    events: EventLog = field(default_factory=EventLog)
    state: str = "queued"
    error: str | None = None
    result: dict | None = None
    pipeline_result: object = None
    found: object = None
    created: float = field(default_factory=time.time)

    @property
    def done(self) -> bool:
        return self.state in ("finished", "failed")


def create_app(
    mode: str | None = None,
    max_concurrent_runs: int = 2,
    max_active_runs: int = 4,
    runs_per_window: int = 5,
    window_s: float = 600,
    keep_runs: int = 100,
) -> FastAPI:
    """The public demo: prepared examples only, rate-limited, bounded in memory and work."""
    mode = mode or os.environ.get("FAULTFORGE_MODE", "demo")
    sandbox_name = os.environ.get("FAULTFORGE_SANDBOX", "local")
    if mode == "live":
        try:
            ensure_isolated_for_live(sandbox_name)
        except SandboxError as error:
            raise RuntimeError(str(error)) from error
    trust_proxy = os.environ.get("FAULTFORGE_TRUST_PROXY") == "1"
    limiter = RateLimiter(runs_per_window, window_s)
    runs: dict[str, Run] = {}
    lock = threading.Lock()
    executor = ThreadPoolExecutor(max_workers=max_concurrent_runs)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="FaultForge", lifespan=lifespan)

    def get_run(run_id: str) -> Run:
        with lock:
            run = runs.get(run_id)
        if run is None:
            raise HTTPException(404, "unknown run")
        return run

    @app.get("/api/info")
    def info() -> dict:
        if mode == "live":
            description = (
                "Live: NVIDIA Nemotron 3 Ultra and Nano on Nebius Token Factory, "
                f"{'Token Factory Sandboxes' if sandbox_name == 'contree' else 'local sandbox'}"
            )
        else:
            description = "Demo: scripted model responses, no Nemotron calls, local sandbox"
        return {"mode": mode, "description": description}

    @app.get("/api/examples")
    def examples() -> list[dict]:
        return [{"id": name, "description": DESCRIPTIONS[name]} for name in sorted(EXAMPLES)]

    @app.post("/api/runs", status_code=202)
    def start(body: RunRequest, request: Request) -> dict:
        if body.example not in EXAMPLES:
            raise HTTPException(404, "unknown example")
        run = Run(id=uuid.uuid4().hex[:12], example=body.example)
        # Capacity check, rate limit and reservation are one critical section, so concurrent
        # requests cannot over-admit. Capacity comes first: retrying against a busy server never
        # burns the client's quota.
        with lock:
            if sum(not r.done for r in runs.values()) >= max_active_runs:
                raise HTTPException(503, "busy running other demos, try again in a minute")
            retry_after = limiter.check(_client_key(request, trust_proxy))
            if retry_after:
                raise HTTPException(
                    429, "too many runs, try again later", {"Retry-After": str(retry_after)}
                )
            runs[run.id] = run
            for stale in list(runs)[:-keep_runs]:
                del runs[stale]
        executor.submit(_execute, run, mode, sandbox_name)
        return {"id": run.id}

    @app.get("/api/runs/{run_id}")
    def status(run_id: str) -> dict:
        run = get_run(run_id)
        return {
            "id": run.id,
            "example": run.example,
            "state": run.state,
            "error": run.error,
            "result": run.result,
        }

    @app.post("/api/runs/{run_id}/pull-request")
    def pull_request(run_id: str) -> dict:
        run = get_run(run_id)
        if run.pipeline_result is None:
            raise HTTPException(409, "run has not finished")
        try:
            plan = plan_pull_request(run.pipeline_result, run.found)
        except PullRequestError as error:
            raise HTTPException(409, str(error)) from error
        # The hosted demo only previews: it never pushes to a repository.
        return open_pull_request(plan, Path("."), dry_run=True)

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str, request: Request) -> StreamingResponse:
        run = get_run(run_id)
        last_seen = request.headers.get("last-event-id", "")

        async def stream():
            # Browsers send Last-Event-ID when they reconnect; resume instead of replaying.
            since = int(last_seen) + 1 if last_seen.isdigit() else 0
            while True:
                fresh = run.events.items(since)
                for event in fresh:
                    payload = {"seq": event.seq, "type": event.type, "data": event.data}
                    yield f"id: {event.seq}\ndata: {json.dumps(payload, default=str)}\n\n"
                since += len(fresh)
                if run.done and not run.events.items(since):
                    yield f"event: end\ndata: {json.dumps({'state': run.state})}\n\n"
                    return
                await asyncio.sleep(0.2)

        return StreamingResponse(stream(), media_type="text/event-stream")

    if WEB_DIST.is_dir():
        app.mount("/", _PageFiles(directory=WEB_DIST, html=True), name="web")
    return app


def _client_key(request: Request, trust_proxy: bool) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if trust_proxy and forwarded:
        # The trusted proxy appends the address it saw; earlier entries are client-supplied.
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _execute(run: Run, mode: str, sandbox_name: str = "local") -> None:
    run.state = "running"
    try:
        assets, repo = EXAMPLES[run.example]
        found = None
        from .cli import REMOTE_SETUP, _live_llm, _researcher, _sandbox

        # Demo mode replays scripted, reviewed patches, so the local sandbox is acceptable there.
        sandbox = _sandbox(sandbox_name) if mode == "live" else LocalSandbox()
        remote = mode == "live" and sandbox_name == "contree"
        setup = REMOTE_SETUP if remote else None
        with sandbox:
            if mode == "live":
                llm = _live_llm()
                found = auto_scenarios(llm, repo, _researcher(), run.events, sandbox, setup)
                scenarios = found.scenarios
            else:
                llm = load_stub(assets / "llm_responses.json")
                files = sorted((assets / "scenarios").glob("*.py"))
                scenarios = [scenario_from_file(p) for p in files]
            if not scenarios:
                raise RuntimeError("no testable scenarios were found")
            result = run_pipeline(repo, scenarios, llm, sandbox, run.events, setup=setup)
        run.pipeline_result, run.found = result, found
        run.result = result_to_dict(result, found)
        run.state = "finished"
    except Exception as error:  # surface any failure to the client instead of hanging
        run.error = str(error)
        run.events.emit("run_failed", error=str(error))  # before the state flips, so streams see it
        run.state = "failed"
