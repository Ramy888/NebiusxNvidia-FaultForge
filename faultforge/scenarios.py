"""Failure scenarios: executable pytest files that use the fault kit."""

import ast
from pathlib import Path

from .llm import LLMError, parse_json
from .models import Scenario
from .repair import collect_source_files

FAULT_CLASSES = {
    "Timeout": "timeout",
    "RateLimit": "rate_limit",
    "Malformed": "malformed",
    "DuplicateDelivery": "duplicate_delivery",
}


def scenario_from_file(path: Path) -> Scenario:
    code = path.read_text()
    tree = ast.parse(code)
    docstring = (ast.get_docstring(tree) or path.stem).strip().splitlines()[0]
    title = docstring.split(":", 1)[-1].strip()
    used = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "faultkit"
        for alias in node.names
    }
    faults = [fault for name, fault in FAULT_CLASSES.items() if name in used]
    return Scenario(
        id=path.stem, title=title, fault=faults[0] if faults else "unknown", test_code=code
    )


# --- Generation -------------------------------------------------------------------------------

FAULT_EXPRESSIONS = {
    "timeout": ("Timeout", "Timeout(on_calls={1}, after_processing=True)"),
    "rate_limit": ("RateLimit", "RateLimit(on_calls={1}, retry_after=1)"),
    "malformed": ("Malformed", "Malformed(on_calls={1})"),
    "duplicate_delivery": ("DuplicateDelivery", "DuplicateDelivery(on_calls={1})"),
}

FAULT_GUIDANCE = {
    "timeout": "The dependency processes the first request, then the response is lost "
    "(httpx.ReadTimeout). Typical invariant: one user operation causes exactly one side effect "
    "at the dependency (len(dependency.accepted) == 1) and the app's own state agrees.",
    "rate_limit": "The first request gets HTTP 429 with Retry-After: 1 and is NOT processed. "
    "Typical invariant: the operation still completes once, or fails with a clear error and "
    "records nothing as successful.",
    "malformed": "The dependency processes the request but returns a truncated JSON body. "
    "Typical invariant: the app never reports success it cannot prove, and does not leak a raw "
    "json.JSONDecodeError to callers (assert on the exception type with pytest.raises).",
    "duplicate_delivery": "The request reaches the dependency twice. Typical invariant: "
    "exactly one side effect at the dependency (the app must make the call idempotent).",
}

TEMPLATE = '''"""FaultForge scenario: {title}"""

import httpx
import pytest
from faultkit import FakeAPI, FaultyTransport, {fault_class}

{imports}


def test_{test_name}():
    dependency = FakeAPI({fake_api_args})
    transport = FaultyTransport(dependency, {fault_expr})
    http = httpx.Client(transport=transport)
{arrange}

{act}

{assertions}
'''

PLAN_SYSTEM = """You design failure-injection tests for one HTTP dependency of a Python backend.
Supported faults: timeout, rate_limit, malformed, duplicate_delivery.
Pick the faults that matter for this dependency and state, for each, the invariant a correct
application must keep. Use the research notes on how the real service behaves when relevant.
Respond with JSON only:
{"scenarios": [{"fault": "timeout", "invariant": "one sentence"}]}"""

WRITE_SYSTEM = """You fill in a pytest template that injects one dependency fault.
The template already provides `dependency` (a fake of the external API whose `.accepted` list
records every request it processed) and `http` (an httpx.Client wired to it with the fault).
`fake_api_args` configures the fake: e.g. `status=200, body={"status": "failed"}` makes every
processed request answer HTTP 200 with that JSON merged into {"id": ..., "status": "accepted"}.
Fill the parts so the test builds the application with `http`, performs the operation once, and
asserts the invariant. Use only names that exist in the application source. Do not catch the
assertion. Give assertions a message that states what went wrong in plain words.
Respond with JSON only:
{"title": "...", "test_name": "snake_case", "fake_api_args": "", "imports": "python import lines",
 "arrange": "python lines", "act": "python lines", "assertions": "python lines"}"""

# Failures caused by the generated test itself, not by the application under the fault.
TEST_BUG_ERRORS = (
    "NameError",
    "ImportError",
    "ModuleNotFoundError",
    "SyntaxError",
    "IndentationError",
    "fixture '",
)


def generate_scenarios(llm, source: Path, dependency, research: str, events) -> list[Scenario]:
    sources = "\n\n".join(
        f"### {p}\n```python\n{c}```" for p, c in collect_source_files(source).items()
    )
    context = (
        f"## Dependency: {dependency.name}\nCalled from: "
        f"{', '.join(s.ref for s in dependency.call_sites)}\n"
        f"Operation at risk: {dependency.operation}\nNotes: {dependency.notes}\n\n"
        f"## Research notes on the real service\n{research or 'none'}\n\n## Source\n{sources}"
    )
    try:
        plan = parse_json(llm.complete("plan", PLAN_SYSTEM, context))
    except LLMError as error:
        events.emit("scenario_planning_failed", reason=str(error))
        return []
    events.emit("scenarios_planned", scenarios=plan.get("scenarios", []))

    scenarios = []
    for item in plan.get("scenarios", []):
        fault = str(item.get("fault", ""))
        if fault not in FAULT_EXPRESSIONS:
            continue
        request = (
            f"{context}\n\n## Fault: {fault}\n{FAULT_GUIDANCE[fault]}\n"
            f"Invariant to assert: {item.get('invariant', '')}\n\n## Template\n```python\n"
            f"{TEMPLATE}```"
        )
        scenario, error = None, ""
        for _ in range(2):
            prompt = request if not error else f"{request}\n\nPrevious answer was invalid: {error}"
            try:
                scenario = _render(fault, parse_json(llm.complete("write", WRITE_SYSTEM, prompt)))
                break
            except (LLMError, ValueError, SyntaxError) as problem:
                error = str(problem)
        if scenario is None:
            events.emit("scenario_discarded", scenario=fault, reason=f"invalid test: {error}")
            continue
        events.emit("scenario_written", scenario=scenario.id, fault=fault, title=scenario.title)
        scenarios.append(scenario)
    return scenarios


def is_test_bug(message: str) -> bool:
    return any(marker in message for marker in TEST_BUG_ERRORS)


def _render(fault: str, fill: dict) -> Scenario:
    fault_class, fault_expr = FAULT_EXPRESSIONS[fault]
    test_name = _slug(str(fill.get("test_name", "")))
    if not test_name:
        raise ValueError("test_name is required")
    code = TEMPLATE.format(
        title=str(fill.get("title", test_name)).replace('"""', "'''"),
        fault_class=fault_class,
        imports=str(fill.get("imports", "")).strip(),
        test_name=test_name,
        fault_expr=fault_expr,
        fake_api_args=str(fill.get("fake_api_args", "")).strip(),
        arrange=_indent(fill.get("arrange", "")),
        act=_indent(fill.get("act", "")),
        assertions=_indent(fill.get("assertions", "")),
    )
    ast.parse(code)
    return Scenario(
        id=f"{fault}_{test_name}"[:80],
        title=str(fill.get("title", test_name)),
        fault=fault,
        test_code=code,
    )


def _indent(block) -> str:
    lines = str(block).strip("\n").splitlines() or ["pass"]
    return "\n".join(f"    {line}" if line.strip() else "" for line in lines)


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")
