"""Plan distinct repair strategies (reasoning model), then write each one (fast model)."""

import json
import re
from pathlib import Path, PurePosixPath

from .events import EventLog
from .llm import LLM, LLMError, Role, parse_json
from .models import Candidate, Scenario
from .sandbox import SandboxError, safe_relative_path

MAX_SOURCE_BYTES = 60_000
# Repairs may not edit tests (that would hide the failure) or the fault kit.
PROTECTED_PREFIXES = ("faultkit/", "tests/")
# ...nor test configuration, which could skip or force-pass the scenarios.
PROTECTED_NAMES = {
    "conftest.py",
    "pytest.ini",
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    "sitecustomize.py",
    "usercustomize.py",
}

PLAN_SYSTEM = """You are a senior backend engineer repairing a reliability bug.
A failure-injection test reproduces how the application misbehaves when an HTTP dependency fails.
Propose distinct repair strategies. Prefer fixes that keep the operation reliable for the user
(for example idempotency keys, safe retries, explicit error handling) over fixes that hide the
failure. Respond with JSON only:
{"strategies": [{"id": "snake_case_id", "summary": "one line", "approach": "what to change"}]}"""

WRITE_SYSTEM = """You implement one repair strategy in a Python codebase.
Return the complete new content of every file you change. Do not modify tests, test
configuration or the faultkit package. Keep the change minimal: keep request bodies, return
values and signatures that existing tests rely on unless the strategy itself requires changing
them. Format each changed file exactly like this:
### relative/path.py
```python
<the complete file>
```"""

_FILE_BLOCK = re.compile(
    r"^#{2,4}\s*`?([\w./-]+\.\w+)`?\s*\n```[\w]*[ \t]*\n(.*?)```", re.DOTALL | re.MULTILINE
)


def parse_files(raw: str) -> dict:
    """Files from `### path` + fenced block pairs; falls back to {"files": {...}} JSON."""
    text = re.sub(r"<think>.*?</think>", "", str(raw), flags=re.DOTALL)
    files = {path: body for path, body in _FILE_BLOCK.findall(text)}
    return {"files": files} if files else parse_json(text)


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
    others: list[tuple[Scenario, str]] = (),
) -> list[Candidate]:
    sources = collect_source_files(source)
    context = _context(sources, scenario, failure, others)
    plan = _ask(llm, "plan", PLAN_SYSTEM, context, _validate_plan)
    strategies = plan["strategies"][:max_candidates]
    events.emit("repairs_planned", strategies=strategies)

    candidates = []
    for strategy in strategies:
        request = f"{context}\n\nImplement this strategy:\n{json.dumps(strategy, indent=2)}"
        try:
            written = _ask(llm, "write", WRITE_SYSTEM, request, _validate_files, parse_files)
        except (RepairError, LLMError) as error:
            events.emit("candidate_rejected", candidate=strategy["id"], reason=str(error))
            continue
        candidate = Candidate(strategy["id"], strategy["summary"], written["files"])
        events.emit("candidate_written", candidate=candidate.id, files=sorted(candidate.files))
        candidates.append(candidate)
    return candidates


def revise_repair(
    llm: LLM,
    source: Path,
    scenario: Scenario,
    failure: str,
    candidate: Candidate,
    verification: str,
    events: EventLog,
    others: list[tuple[Scenario, str]] = (),
) -> Candidate | None:
    """Give a rejected repair one more attempt, showing the writer what verification found."""
    current = "\n\n".join(f"### {p}\n```python\n{c}```" for p, c in candidate.files.items())
    request = (
        f"{_context(collect_source_files(source), scenario, failure, others)}\n\n"
        f"## Strategy\n{candidate.summary}\n\n## Your previous patch\n{current}\n\n"
        f"## Verification of that patch\n{verification}\n\n"
        "First work out why the previous patch did not change the failing behaviour (for "
        "example a new parameter that no caller passes, or a fix in the wrong layer). Then "
        "revise it so the failure scenarios pass and the existing tests still pass, changing "
        "every file that needs it. Return the complete revised files."
    )
    try:
        written = _ask(llm, "fix", WRITE_SYSTEM, request, _validate_files, parse_files)
    except (RepairError, LLMError) as error:
        events.emit("candidate_rejected", candidate=f"{candidate.id}_revised", reason=str(error))
        return None
    revised = Candidate(f"{candidate.id}_revised", candidate.summary, written["files"])
    events.emit("candidate_revised", candidate=revised.id, files=sorted(revised.files))
    return revised


def _context(
    sources: dict[str, str],
    scenario: Scenario,
    failure: str,
    others: list[tuple[Scenario, str]] = (),
) -> str:
    listing = "\n\n".join(f"### {path}\n```python\n{code}```" for path, code in sources.items())
    failures = [(scenario, failure), *[o for o in others if o[0].id != scenario.id]]
    shown = "\n\n".join(
        f"### {s.title} (fault: {s.fault}) — {s.test_path}\n```python\n{s.test_code}```\n"
        f"Observed: {message}"
        for s, message in failures
    )
    return f"## Reproduced failures\n{shown}\n\n## Application source\n{listing}"


def _ask(llm: LLM, role: Role, system: str, user: str, validate, parse=parse_json) -> dict:
    prompt = user
    for attempt in range(2):
        raw = llm.complete(role, system, prompt)
        try:
            data = parse(raw)
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
    """Validates, and normalises in place, the model's file contents."""
    from .codefix import normalize_code

    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("expected a non-empty 'files' object")
    for path, content in list(files.items()):
        safe = safe_relative_path(path).as_posix()
        if safe.startswith(PROTECTED_PREFIXES) or PurePosixPath(safe).name in PROTECTED_NAMES:
            raise ValueError(f"must not modify {path}")
        if not isinstance(content, str):
            raise ValueError(f"content for {path} must be a string")
        files[path] = normalize_code(content) + "\n"
        if path.endswith(".py"):
            try:
                compile(files[path], path, "exec")
            except SyntaxError as error:
                raise ValueError(
                    f"syntax error in {path} line {error.lineno}: {error.msg}"
                ) from None
