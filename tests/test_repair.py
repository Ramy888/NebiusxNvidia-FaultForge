import json
from pathlib import Path

import pytest

from faultforge.demo import ORDER_SERVICE
from faultforge.events import EventLog
from faultforge.llm import StubLLM, parse_json
from faultforge.models import Scenario
from faultforge.repair import RepairError, collect_source_files, generate_repairs

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "order-service"
SCENARIO = Scenario(
    id="timeout_duplicate",
    title="Provider accepts the order but the response times out",
    fault="timeout",
    test_code=(ORDER_SERVICE / "scenarios" / "timeout_duplicate.py").read_text(),
)
FAILURE = "AssertionError: one order created 2 fulfillments at the provider"
STRATEGIES = json.dumps(
    {
        "strategies": [
            {"id": "idempotency_key", "summary": "Send an idempotency key", "approach": "..."},
            {"id": "no_retry", "summary": "Stop retrying", "approach": "..."},
        ]
    }
)


def patch(path: str, content: str = "x = 1\n") -> str:
    return json.dumps({"files": {path: content}})


def test_one_candidate_per_planned_strategy():
    llm = StubLLM(
        plan=[STRATEGIES],
        write=[patch("orders/fulfillment.py"), patch("orders/service.py")],
    )

    candidates = generate_repairs(llm, EXAMPLE, SCENARIO, FAILURE, EventLog())

    assert [c.id for c in candidates] == ["idempotency_key", "no_retry"]
    assert candidates[0].files == {"orders/fulfillment.py": "x = 1\n"}


def test_planner_sees_the_failure_and_the_source():
    llm = StubLLM(plan=[STRATEGIES], write=[patch("orders/a.py"), patch("orders/b.py")])

    generate_repairs(llm, EXAMPLE, SCENARIO, FAILURE, EventLog())

    plan_prompt = llm.calls[0].user
    assert FAILURE in plan_prompt
    assert "class OrderService" in plan_prompt
    assert SCENARIO.test_code in plan_prompt


def test_malformed_output_is_retried_once():
    llm = StubLLM(
        plan=["not json at all", STRATEGIES],
        write=[patch("orders/a.py"), patch("orders/b.py")],
    )

    candidates = generate_repairs(llm, EXAMPLE, SCENARIO, FAILURE, EventLog())

    assert len(candidates) == 2
    assert "could not be parsed" in llm.calls[1].user


def test_malformed_output_twice_is_an_error():
    llm = StubLLM(plan=["nope", "still nope"])

    with pytest.raises(RepairError):
        generate_repairs(llm, EXAMPLE, SCENARIO, FAILURE, EventLog())


def test_patch_outside_the_repo_is_refused():
    llm = StubLLM(
        plan=[STRATEGIES],
        write=[patch("../../etc/passwd"), patch("../x.py"), patch("orders/service.py")],
    )
    events = EventLog()

    candidates = generate_repairs(llm, EXAMPLE, SCENARIO, FAILURE, events)

    assert [c.id for c in candidates] == ["no_retry"]
    assert any(e.type == "candidate_rejected" for e in events.items())


def test_patch_editing_the_scenario_test_or_fault_kit_is_refused():
    llm = StubLLM(
        plan=[STRATEGIES],
        write=[
            patch(SCENARIO.test_path),
            patch(SCENARIO.test_path),
            patch("faultkit/api.py"),
            patch("faultkit/api.py"),
        ],
    )

    assert generate_repairs(llm, EXAMPLE, SCENARIO, FAILURE, EventLog()) == []


def test_parse_json_strips_reasoning_and_code_fences():
    raw = '<think>let me think {not json}</think>\nSure:\n```json\n{"a": 1}\n```'

    assert parse_json(raw) == {"a": 1}


def test_source_files_exclude_tests_and_virtualenvs():
    files = collect_source_files(EXAMPLE)

    assert "orders/service.py" in files
    assert not any(path.startswith(("tests/", ".venv/")) for path in files)


def test_stub_answers_fix_requests_from_its_write_queue_unless_given_fix_answers():
    llm = StubLLM(write=["from write"])
    assert llm.complete("fix", "s", "u") == "from write"

    llm = StubLLM(write=["from write"], fix=["from fix"])
    assert llm.complete("fix", "s", "u") == "from fix"
