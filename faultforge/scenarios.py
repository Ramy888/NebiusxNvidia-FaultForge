"""Failure scenarios: executable pytest files that use the fault kit."""

import ast
import re
from pathlib import Path

from .codefix import add_missing_imports, extract_code, normalize_code, top_level_symbols
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

FAULT_KIT_DOC = """Fault kit API (importable as `faultkit`):
- FakeAPI(status=201, id_prefix="res", body=None): an in-process fake of the external service.
  It answers `status` with JSON {"id": "<id_prefix>_<n>", "status": "accepted", **body}.
  `.accepted` is the list of REQUEST bodies it processed (what the application sent; these
  have no "id"). `.created` is the list of objects it created, each with its "id": use it to
  check which ID the application stored. It honours the Idempotency-Key header: a repeated key
  returns the first result and is not processed again (not added to .accepted or .created).
- FaultyTransport(handler, *faults): an httpx transport. Use it as
  httpx.Client(transport=FaultyTransport(fake, fault)).
- Timeout(on_calls={1}, after_processing=True): the request is processed, then httpx.ReadTimeout.
- RateLimit(on_calls={1}, retry_after=1): HTTP 429 with Retry-After; the request is NOT processed.
- Malformed(on_calls={1}): the request is processed, the response body is truncated JSON.
- DuplicateDelivery(on_calls={1}): the request reaches the fake twice."""

# A worked example for an application that is NOT the one under test, so it teaches the shape
# of a good scenario without leaking an answer.
EXAMPLE_TEST = '''"""FaultForge scenario: the warehouse reserves stock but the response times out"""

import httpx
from faultkit import FakeAPI, FaultyTransport, Timeout

from inventory.client import WarehouseClient
from inventory.reservations import ReservationService


def test_one_checkout_reserves_stock_once_when_the_response_times_out():
    warehouse = FakeAPI(status=201)
    http = httpx.Client(
        transport=FaultyTransport(warehouse, Timeout(on_calls={1}, after_processing=True))
    )
    service = ReservationService(WarehouseClient(http, base_url="https://warehouse.test"))

    reservation = service.reserve("sku-1", quantity=2)

    assert len(warehouse.accepted) == 1, (
        f"one checkout reserved stock {len(warehouse.accepted)} times at the warehouse"
    )
    assert reservation.status == "reserved", "the checkout did not end up reserved"
    assert reservation.warehouse_id == warehouse.created[0]["id"], (
        "the checkout does not reference the reservation the warehouse created"
    )
'''

PLAN_SYSTEM = """You design failure-injection tests for one HTTP dependency of a Python backend.
Supported faults: timeout, rate_limit, malformed, duplicate_delivery.
Pick the faults that matter for this dependency and state, for each, the invariant a correct
application must keep. Use the research notes on how the real service behaves when relevant.
State invariants about side effects at the dependency and about the application's recorded
state (e.g. "the order is not marked paid", "exactly one fulfillment exists"), never about how
many requests were sent: retrying is legitimate. Raising an error the caller can retry is an
acceptable outcome; recording a wrong result is not.
Respond with JSON only:
{"scenarios": [{"fault": "timeout", "invariant": "one sentence"}]}"""

WRITE_SYSTEM = """You write one pytest file that injects one dependency fault into a Python
application and asserts one invariant. Build the application's real classes, giving them an
httpx.Client whose transport is a FaultyTransport around a FakeAPI. Perform the user operation
once. Use only names that exist in the application source and the fault kit. The test must fail
only when the application breaks the invariant; give each assertion a plain-words message.
Count side effects with len(fake.accepted), never requests: a retry legitimately sends the
request again, and an idempotency key makes the fake ignore the repeat. If raising an error is
an acceptable outcome, wrap the operation in `try: ... except Exception: pass` and assert on the
resulting state afterwards.
Start the file with a docstring: \"\"\"FaultForge scenario: <what goes wrong>\"\"\".
Reply with exactly one ```python code block containing the complete file, nothing else."""

FAULT_KIT_SYMBOLS = {
    "FakeAPI": "faultkit",
    "FaultyTransport": "faultkit",
    "Timeout": "faultkit",
    "RateLimit": "faultkit",
    "Malformed": "faultkit",
    "DuplicateDelivery": "faultkit",
    "httpx": "httpx",
    "pytest": "pytest",
}

# Failures caused by the generated test itself, not by the application under the fault.
TEST_BUG_ERRORS = (
    "NameError",
    "ImportError",
    "ModuleNotFoundError",
    "SyntaxError",
    "IndentationError",
    "fixture '",
)

FAULT_KIT_NAMES = (
    "FakeAPI",
    "FaultyTransport",
    "Timeout(",
    "RateLimit(",
    "Malformed(",
    "DuplicateDelivery(",
)


class ScenarioWriter:
    """Plans scenarios with the reasoning model; writes and fixes test files with the writer."""

    def __init__(self, llm, source: Path, dependency, research: str, events):
        self.llm, self.source, self.events = llm, source, events
        self.symbols = top_level_symbols(source) | FAULT_KIT_SYMBOLS
        sources = "\n\n".join(
            f"### {p}\n```python\n{c}```" for p, c in collect_source_files(source).items()
        )
        self.context = (
            f"## Dependency: {dependency.name}\nCalled from: "
            f"{', '.join(s.ref for s in dependency.call_sites)}\n"
            f"Operation at risk: {dependency.operation}\nNotes: {dependency.notes}\n\n"
            f"## Research notes on the real service\n{research or 'none'}\n\n## Source\n{sources}"
        )
        self._requests: dict[str, tuple[str, str, str]] = {}

    def write_all(self) -> list[Scenario]:
        try:
            plan = parse_json(self.llm.complete("plan", PLAN_SYSTEM, self.context))
        except LLMError as error:
            self.events.emit("scenario_planning_failed", reason=str(error))
            return []
        items = plan.get("scenarios")
        items = [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
        self.events.emit("scenarios_planned", scenarios=items)
        scenarios = []
        for item in items:
            fault = str(item.get("fault", ""))
            if fault not in FAULT_EXPRESSIONS:
                continue
            invariant = str(item.get("invariant", ""))
            request = self._request(fault, invariant)
            scenario = self._write(fault, invariant, request)
            if scenario is None:
                continue
            self._requests[scenario.id] = (fault, invariant, request)
            self._announce("scenario_written", scenario)
            scenarios.append(scenario)
        return scenarios

    def fix(self, scenario: Scenario, output: str) -> Scenario | None:
        """Send a test that broke for its own reasons back to the writer, with the error."""
        fault, invariant, request = self._requests.get(
            scenario.id, (scenario.fault, scenario.title, self._request(scenario.fault, ""))
        )
        prompt = (
            f"{request}\n\n## Your previous file\n```python\n{scenario.test_code}```\n\n"
            f"## It is broken. pytest output:\n```\n{output[-3000:]}\n```\n"
            "The failure comes from a mistake in the test, not from the application. "
            "Return the corrected complete file."
        )
        fixed = self._write(fault, invariant, prompt, attempts=1, role="fix")
        if fixed is None:
            return None
        fixed = Scenario(scenario.id, fixed.title, fixed.fault, fixed.test_code)
        self._announce("scenario_fixed", fixed)
        return fixed

    def _request(self, fault: str, invariant: str) -> str:
        _, fault_expr = FAULT_EXPRESSIONS[fault]
        return (
            f"{self.context}\n\n## Fault to inject: {fault}\n{FAULT_GUIDANCE[fault]}\n"
            f"Use exactly this fault: `{fault_expr}`\nInvariant to assert: {invariant}\n\n"
            f"## {FAULT_KIT_DOC}\n\n## Example for a different application\n```python\n"
            f"{EXAMPLE_TEST}```"
        )

    def _write(
        self, fault: str, invariant: str, request: str, attempts: int = 2, role: str = "write"
    ):
        error = ""
        for _ in range(attempts):
            prompt = (
                request if not error else f"{request}\n\nYour previous answer was invalid: {error}"
            )
            try:
                raw = self.llm.complete(role, WRITE_SYSTEM, prompt)
                return build_scenario(fault, raw, invariant, self.symbols)
            except (LLMError, ValueError, SyntaxError) as problem:
                error = str(problem)
        self.events.emit("scenario_discarded", scenario=fault, reason=f"invalid test: {error}")
        return None

    def _announce(self, kind: str, scenario: Scenario) -> None:
        self.events.emit(
            kind,
            scenario=scenario.id,
            fault=scenario.fault,
            title=scenario.title,
            test_code=scenario.test_code,
        )


def generate_scenarios(llm, source: Path, dependency, research: str, events) -> list[Scenario]:
    return ScenarioWriter(llm, source, dependency, research, events).write_all()


def build_scenario(fault: str, raw: str, invariant: str, symbols: dict[str, str]) -> Scenario:
    code = normalize_code(extract_code(raw))
    tree = ast.parse(code)
    tests = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test")]
    if not tests:
        raise ValueError("the file has no test function")
    fault_class, _ = FAULT_EXPRESSIONS[fault]
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    if fault_class not in used or "FaultyTransport" not in used:
        raise ValueError(f"the test must inject {fault_class} through a FaultyTransport")
    code = add_missing_imports(code + "\n", symbols | FAULT_KIT_SYMBOLS)
    docstring = (ast.get_docstring(tree) or invariant or fault).strip().splitlines()[0]
    title = docstring.split(":", 1)[-1].strip() if ":" in docstring else docstring
    name = _slug(tests[0].name.removeprefix("test_").removeprefix("test"))
    return Scenario(id=f"{fault}_{name}"[:80], title=title, fault=fault, test_code=code)


def is_test_bug(message: str) -> bool:
    if any(marker in message for marker in TEST_BUG_ERRORS):
        return True
    # Calling something that does not exist in httpx, pytest or the fault kit.
    if message.startswith("AttributeError: module '") and any(
        f"module '{m}'" in message for m in ("httpx", "pytest", "faultkit")
    ):
        return True
    # A TypeError about the fault kit's own API means the generated test misused it.
    return message.startswith("TypeError") and any(n in message for n in FAULT_KIT_NAMES)


_FRAME = re.compile(r"^(\S+\.py):\d+: in ", re.MULTILINE)
ASSERTION_FAILURES = ("AssertionError", "assert ", "Failed: DID NOT RAISE")


def raised_in_test_code(output: str, test_path: str) -> bool:
    """True when the innermost traceback frame is the test file itself, not application code."""
    first_error = output.find("\nE ")
    frames = _FRAME.findall(output[: first_error if first_error != -1 else len(output)])
    return bool(frames) and frames[-1].endswith(test_path)


def scenario_is_broken(check, test_path: str | None = None) -> bool:
    """A scenario that errors, times out or fails because of its own bug proves nothing.

    An exception other than an assertion, raised by the test's own code (e.g. KeyError on a
    dict the test built itself), is a test bug; the same exception raised inside application
    code is a genuine failure under the fault.
    """
    from .replay import Outcome

    if check.outcome in (Outcome.ERROR, Outcome.TIMED_OUT):
        return True
    if check.outcome is not Outcome.FAILED:
        return False
    if is_test_bug(check.message):
        return True
    return (
        test_path is not None
        and not check.message.startswith(ASSERTION_FAILURES)
        and raised_in_test_code(check.output, test_path)
    )


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")
