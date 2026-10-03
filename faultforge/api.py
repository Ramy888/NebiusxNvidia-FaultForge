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

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auto import auto_scenarios
from .demo import DESCRIPTIONS, EXAMPLES
from .events import EventLog
from .pipeline import load_stub, run_pipeline
from .pr import PullRequestError, open_pull_request, plan_pull_request
from .sandbox import LocalSandbox
from .scenarios import scenario_from_file
from .serialize import result_to_dict

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


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


def create_app(mode: str | None = None, max_concurrent_runs: int = 2) -> FastAPI:
    mode = mode or os.environ.get("FAULTFORGE_MODE", "demo")
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

    @app.get("/api/examples")
    def examples() -> list[dict]:
        return [{"id": name, "description": DESCRIPTIONS[name]} for name in sorted(EXAMPLES)]

    @app.post("/api/runs", status_code=202)
    def start(request: RunRequest) -> dict:
        if request.example not in EXAMPLES:
            raise HTTPException(404, "unknown example")
        run = Run(id=uuid.uuid4().hex[:12], example=request.example)
        with lock:
            runs[run.id] = run
        executor.submit(_execute, run, mode)
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
    async def events(run_id: str) -> StreamingResponse:
        run = get_run(run_id)

        async def stream():
            since = 0
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
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app


def _execute(run: Run, mode: str) -> None:
    run.state = "running"
    try:
        assets, repo = EXAMPLES[run.example]
        found = None
        if mode == "live":
            from .cli import _live_llm, _researcher

            llm = _live_llm()
            found = auto_scenarios(llm, repo, _researcher(), run.events)
            scenarios = found.scenarios
        else:
            llm = load_stub(assets / "llm_responses.json")
            scenarios = [scenario_from_file(p) for p in sorted((assets / "scenarios").glob("*.py"))]
        if not scenarios:
            raise RuntimeError("no testable scenarios were found")
        with LocalSandbox() as sandbox:
            result = run_pipeline(repo, scenarios, llm, sandbox, run.events)
        run.pipeline_result, run.found = result, found
        run.result = result_to_dict(result, found)
        run.state = "finished"
    except Exception as error:  # surface any failure to the client instead of hanging
        run.error = str(error)
        run.state = "failed"
        run.events.emit("run_failed", error=str(error))
