"""Model-written code is normalised before use; these cover the failures seen in live runs."""

import ast
import json
from pathlib import Path

from faultforge.codefix import add_missing_imports, normalize_code, top_level_symbols
from faultforge.events import EventLog
from faultforge.llm import StubLLM
from faultforge.models import Scenario
from faultforge.repair import generate_repairs, parse_files
from faultforge.scenarios import build_scenario

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "order-service"


def test_literal_newline_escapes_become_real_newlines():
    assert normalize_code("a = 1\\nb = 2") == "a = 1\nb = 2"


def test_real_code_with_escapes_inside_strings_is_left_alone():
    code = 'print("x\\ny")\nz = 1'
    assert normalize_code(code) == code


def test_uniformly_indented_blocks_are_dedented():
    assert normalize_code("    a = 1\n    b = 2\n") == "a = 1\nb = 2"


def test_symbols_map_names_to_their_modules():
    symbols = top_level_symbols(EXAMPLE)

    assert symbols["FulfillmentClient"] == "orders.fulfillment"
    assert symbols["OrderService"] == "orders.service"


def test_missing_application_imports_are_added():
    code = "import httpx\n\ndef test():\n    FulfillmentClient(httpx.Client(), base_url='x')\n"

    fixed = add_missing_imports(code, top_level_symbols(EXAMPLE))

    assert "from orders.fulfillment import FulfillmentClient" in fixed
    ast.parse(fixed)


def test_extracted_scenario_survives_the_live_failure_modes():
    raw = (
        "<think>hmm</think>Sure!\n```python\n"
        "from faultkit import FaultyTransport, DuplicateDelivery\nimport httpx\n"
        "from orders.service import OrderService\n\n"
        "def test_duplicate_delivery():\n    dependency = FakeAPI()\n"
        "    http = httpx.Client(transport=FaultyTransport(dependency, DuplicateDelivery()))\n"
        "    service = OrderService(FulfillmentClient(http, base_url='http://x'))\n"
        "    service.place_order('c', [])\n"
        "    assert len(dependency.accepted) == 1, 'two fulfillments'\n```"
    )

    scenario = build_scenario(
        "duplicate_delivery", raw, "one fulfillment", top_level_symbols(EXAMPLE)
    )

    ast.parse(scenario.test_code)
    assert "from faultkit import FakeAPI" in scenario.test_code
    assert "from orders.fulfillment import FulfillmentClient" in scenario.test_code
    assert scenario.id == "duplicate_delivery_duplicate_delivery"


def test_files_can_be_returned_as_fenced_blocks():
    raw = "### orders/a.py\n```python\nA = 1\n```\n\n### `orders/b.py`\n```python\nB = 2\n```"

    assert parse_files(raw) == {"files": {"orders/a.py": "A = 1\n", "orders/b.py": "B = 2\n"}}


def test_patches_with_syntax_errors_are_retried_then_rejected():
    plan = json.dumps({"strategies": [{"id": "a", "summary": "A"}]})
    broken = json.dumps({"files": {"orders/service.py": "def f(:\n    pass\n"}})
    events = EventLog()

    candidates = generate_repairs(
        StubLLM(plan=[plan], write=[broken, broken]),
        EXAMPLE,
        Scenario("s", "t", "timeout", ""),
        "f",
        events,
    )

    assert candidates == []
    assert (
        "syntax"
        in [e for e in events.items() if e.type == "candidate_rejected"][0].data["reason"].lower()
    )


def test_patches_with_escaped_newlines_are_normalised():
    plan = json.dumps({"strategies": [{"id": "a", "summary": "A"}]})
    escaped = json.dumps({"files": {"orders/x.py": "a = 1\\nb = 2\\n"}})

    [candidate] = generate_repairs(
        StubLLM(plan=[plan], write=[escaped]),
        EXAMPLE,
        Scenario("s", "t", "timeout", ""),
        "f",
        EventLog(),
    )

    assert candidate.files["orders/x.py"] == "a = 1\nb = 2\n"
