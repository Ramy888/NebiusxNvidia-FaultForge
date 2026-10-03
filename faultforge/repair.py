"""Plan distinct repair strategies (reasoning model), then write each one (fast model)."""

import json
from pathlib import Path

from .events import EventLog
from .llm import LLM, LLMError, Role, parse_json
from .models import Candidate, Scenario
from .sandbox import SandboxError, safe_relative_path

MAX_SOURCE_BYTES = 60_000
# Repairs may not edit tests (that would hide the failure) or the fault kit.
PROTECTED_PREFIXES = ("faultkit/", "tests/")

PLAN_SYSTEM = """You are a senior backend engineer repairing a reliability bug.
A failure-injection test reproduces how the application misbehaves when an HTTP dependency fails.
Propose distinct repair strategies. Prefer fixes that keep the operation reliable for the user
(for example idempotency keys, safe retries, explicit error handling) over fixes that hide the
failure. Respond with JSON only:
{"strategies": [{"id": "snake_case_id", "summary": "one line", "approach": "what to change"}]}"""

WRITE_SYSTEM = """You implement one repair strategy in a Python codebase.
Return the complete new content of every file you change. Do not modify tests or the faultkit
package. Keep the change minimal and keep existing behaviour that the tests rely on.
Respond with JSON only: {"files": {"relative/path.py": "full new file content"}}"""


class RepairError(Exception):
    pass


def collect_source_files(source: Path) -> dict[str, str]:
    files, total = {}, 0
    for path in sorted(source.rglob("*.py")):
        relative = path.relative_to(source).as_posix()
        if relative.startswith(("tests/", ".venv/", "faultkit/")) or "/." in f"/{relative}":
            continue
        content = path.read_text()
        total += len(content)
        if total > MAX_SOURCE_BYTES:
            break
        files[relative] = content
    return files


def generate_repairs(
    llm: LLM,
    source: Path,
    scenario: Scenario,
    failure: str,
    events: EventLog,
    max_candidates: int = 3,
) -> list[Candidate]:
    sources = collect_source_files(source)
    context = _context(sources, scenario, failure)
    plan = _ask(llm, "plan", PLAN_SYSTEM, context, _validate_plan)
    strategies = plan["strategies"][:max_candidates]
    events.emit("repairs_planned", strategies=strategies)

    candidates = []
    for strategy in strategies:
        request = f"{context}\n\nImplement this strategy:\n{json.dumps(strategy, indent=2)}"
        try:
            written = _ask(llm, "write", WRITE_SYSTEM, request, _validate_files)
        except RepairError as error:
            events.emit("candidate_rejected", candidate=strategy["id"], reason=str(error))
            continue
        candidate = Candidate(strategy["id"], strategy["summary"], written["files"])
        events.emit("candidate_written", candidate=candidate.id, files=sorted(candidate.files))
        candidates.append(candidate)
    return candidates


def _context(sources: dict[str, str], scenario: Scenario, failure: str) -> str:
    listing = "\n\n".join(f"### {path}\n```python\n{code}```" for path, code in sources.items())
    return (
        f"## Failure scenario: {scenario.title} (fault: {scenario.fault})\n"
        f"### {scenario.test_path}\n```python\n{scenario.test_code}```\n\n"
        f"## Observed failure\n{failure}\n\n## Application source\n{listing}"
    )


def _ask(llm: LLM, role: Role, system: str, user: str, validate) -> dict:
    prompt = user
    for attempt in range(2):
        raw = llm.complete(role, system, prompt)
        try:
            data = parse_json(raw)
            validate(data)
            return data
        except (LLMError, ValueError, SandboxError) as error:
            if attempt == 1:
                raise RepairError(f"model output rejected twice: {error}") from error
            prompt = f"{user}\n\nYour previous answer could not be parsed or was invalid: {error}"
    raise AssertionError("unreachable")


def _validate_plan(data: dict) -> None:
    strategies = data.get("strategies")
    if not isinstance(strategies, list) or not strategies:
        raise ValueError("expected a non-empty 'strategies' list")
    for strategy in strategies:
        if not all(isinstance(strategy.get(k), str) for k in ("id", "summary")):
            raise ValueError("each strategy needs string 'id' and 'summary'")


def _validate_files(data: dict) -> None:
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("expected a non-empty 'files' object")
    for path, content in files.items():
        safe = safe_relative_path(path).as_posix()
        if safe.startswith(PROTECTED_PREFIXES):
            raise ValueError(f"must not modify {path}")
        if not isinstance(content, str):
            raise ValueError(f"content for {path} must be a string")
