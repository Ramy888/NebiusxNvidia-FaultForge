import ast
import json

from faultforge.demo import ORDER_SERVICE, ORDER_SERVICE_REPO
from faultforge.discovery import CallSite, Dependency
from faultforge.events import EventLog
from faultforge.llm import StubLLM
from faultforge.pipeline import Status, load_stub, run_pipeline
from faultforge.sandbox import LocalSandbox
from faultforge.scenarios import generate_scenarios

DEPENDENCY = Dependency(
    name="fulfillment provider",
    operation="orders.service:OrderService.place_order",
    notes="retries on timeout",
    call_sites=[
        CallSite("orders/fulfillment.py", 11, "FulfillmentClient.create_fulfillment", "post", "")
    ],
)
PLAN = json.dumps(
    {
        "scenarios": [
            {"fault": "timeout", "invariant": "one order creates exactly one fulfillment"},
            {"fault": "malformed", "invariant": "a garbled response never confirms an order"},
            {"fault": "earthquake", "invariant": "not a supported fault"},
        ]
    }
)
# The writer answers with a fenced Python file, as Nemotron does in live runs.
GOOD_FILL = """Here is the test:
```python
\"\"\"FaultForge scenario: the provider accepts an order but the response times out\"\"\"

import httpx
from faultkit import FakeAPI, FaultyTransport, Timeout

from orders.service import OrderService


def test_one_order_creates_one_fulfillment_when_response_times_out():
    dependency = FakeAPI()
    transport = FaultyTransport(dependency, Timeout(on_calls={1}, after_processing=True))
    service = OrderService(FulfillmentClient(httpx.Client(transport=transport), base_url="https://f.test"))

    order = service.place_order("cus_1", [{"sku": "MUG-01", "qty": 1}])

    assert len(dependency.accepted) == 1, (
        f"one order created {len(dependency.accepted)} fulfillments at the provider"
    )
    assert order.status == "confirmed"
```"""
BUGGY_FILL = """```python
\"\"\"FaultForge scenario: garbled provider response\"\"\"
from faultkit import FakeAPI, FaultyTransport, Malformed


def test_garbled_response_never_confirms():
    http = httpx.Client(transport=FaultyTransport(FakeAPI(), Malformed(on_calls={1})))
    order = svc.place_order("cus_1", [])
    assert order.status != "confirmed"
```"""


def test_one_scenario_per_supported_planned_fault():
    llm = StubLLM(plan=[PLAN], write=[GOOD_FILL, BUGGY_FILL])

    scenarios = generate_scenarios(llm, ORDER_SERVICE_REPO, DEPENDENCY, "", EventLog())

    assert [s.fault for s in scenarios] == ["timeout", "malformed"]
    assert scenarios[0].id == "timeout_one_order_creates_one_fulfillment_when_response_times_out"
    assert scenarios[0].title == "the provider accepts an order but the response times out"


def test_rendered_scenarios_are_valid_python_using_the_fault_kit():
    llm = StubLLM(plan=[PLAN], write=[GOOD_FILL, BUGGY_FILL])

    [timeout, _] = generate_scenarios(llm, ORDER_SERVICE_REPO, DEPENDENCY, "", EventLog())

    ast.parse(timeout.test_code)
    assert "Timeout(on_calls={1}, after_processing=True)" in timeout.test_code
    assert "from orders.fulfillment import FulfillmentClient" in timeout.test_code


def test_fill_that_is_not_valid_python_is_retried_then_dropped():
    broken = "```python\ndef test_x(:\n    pass\n```"
    llm = StubLLM(
        plan=[json.dumps({"scenarios": [{"fault": "timeout", "invariant": "x"}]})],
        write=[broken, broken],
    )
    events = EventLog()

    assert generate_scenarios(llm, ORDER_SERVICE_REPO, DEPENDENCY, "", events) == []
    assert any(e.type == "scenario_discarded" for e in events.items())


def test_research_notes_reach_the_planner():
    llm = StubLLM(plan=[PLAN], write=[GOOD_FILL, BUGGY_FILL])

    generate_scenarios(
        llm, ORDER_SERVICE_REPO, DEPENDENCY, "Retry-After is sent on 429", EventLog()
    )

    assert "Retry-After is sent on 429" in llm.calls[0].user


def test_scenario_failing_for_a_test_bug_is_discarded_and_the_real_one_repaired():
    scenario_llm = StubLLM(plan=[PLAN], write=[GOOD_FILL, BUGGY_FILL])
    scenarios = generate_scenarios(scenario_llm, ORDER_SERVICE_REPO, DEPENDENCY, "", EventLog())
    events = EventLog()

    with LocalSandbox() as sandbox:
        result = run_pipeline(
            ORDER_SERVICE_REPO,
            scenarios,
            load_stub(ORDER_SERVICE / "llm_responses.json"),
            sandbox,
            events,
        )

    discarded = [e.data["scenario"] for e in events.items() if e.type == "scenario_discarded"]
    assert discarded == ["malformed_garbled_response_never_confirms"]
    assert [s.fault for s in result.scenarios] == ["timeout"]
    assert result.status is Status.REPAIRED


def test_a_test_that_must_use_the_planned_fault_is_rejected_otherwise():
    plan = json.dumps({"scenarios": [{"fault": "rate_limit", "invariant": "x"}]})
    no_fault = "```python\ndef test_nothing():\n    assert True\n```"
    llm = StubLLM(plan=[plan], write=[no_fault, no_fault])

    assert generate_scenarios(llm, ORDER_SERVICE_REPO, DEPENDENCY, "", EventLog()) == []
    assert "RateLimit" in llm.calls[-1].user


def test_broken_scenarios_are_sent_back_with_the_error_and_fixed():
    from faultforge.auto import validate_scenarios
    from faultforge.scenarios import ScenarioWriter

    writer = ScenarioWriter(
        StubLLM(
            plan=[PLAN],
            write=[
                GOOD_FILL,
                BUGGY_FILL,
                GOOD_FILL.replace("timeout", "malformed")
                .replace("Timeout(on_calls={1}, after_processing=True)", "Malformed(on_calls={1})")
                .replace("Timeout", "Malformed"),
            ],
        ),
        ORDER_SERVICE_REPO,
        DEPENDENCY,
        "",
        events := EventLog(),
    )
    scenarios = writer.write_all()

    with LocalSandbox() as sandbox:
        kept = validate_scenarios(writer, sandbox, ORDER_SERVICE_REPO, scenarios, events)

    fixed = [e for e in events.items() if e.type == "scenario_fixed"]
    fix_calls = [c for c in writer.llm.calls if c.role == "fix"]
    assert fixed and "NameError" in fix_calls[-1].user
    assert {s.fault for s in kept} == {"timeout", "malformed"}


def test_a_test_crashing_in_its_own_code_is_sent_back_and_dropped_if_unfixed():
    from faultforge.auto import validate_scenarios
    from faultforge.scenarios import ScenarioWriter

    always_fails = """```python
\"\"\"FaultForge scenario: setup mistake\"\"\"
import httpx
from faultkit import FakeAPI, FaultyTransport, Timeout


def test_lookup_of_an_order_that_was_never_created():
    http = httpx.Client(transport=FaultyTransport(FakeAPI(), Timeout(on_calls={1})))
    orders = {}
    assert orders["order-456"] == "paid", "never reached"
```"""
    plan = json.dumps({"scenarios": [{"fault": "timeout", "invariant": "x"}]})
    events = EventLog()
    writer = ScenarioWriter(
        StubLLM(plan=[plan], write=[always_fails, always_fails]),
        ORDER_SERVICE_REPO,
        DEPENDENCY,
        "",
        events,
    )
    scenarios = writer.write_all()

    with LocalSandbox() as sandbox:
        kept = validate_scenarios(writer, sandbox, ORDER_SERVICE_REPO, scenarios, events)

    assert kept == []
    assert "KeyError" in writer.llm.calls[-1].user


def test_a_genuine_scenario_passes_its_control_run_and_is_kept():
    from faultforge.auto import validate_scenarios
    from faultforge.scenarios import ScenarioWriter

    plan = json.dumps({"scenarios": [{"fault": "timeout", "invariant": "one fulfillment"}]})
    events = EventLog()
    writer = ScenarioWriter(
        StubLLM(plan=[plan], write=[GOOD_FILL]), ORDER_SERVICE_REPO, DEPENDENCY, "", events
    )

    with LocalSandbox() as sandbox:
        kept = validate_scenarios(writer, sandbox, ORDER_SERVICE_REPO, writer.write_all(), events)

    assert [s.fault for s in kept] == ["timeout"]


def test_a_test_expecting_an_error_from_the_fault_is_kept():
    from faultforge.auto import validate_scenarios
    from faultforge.scenarios import ScenarioWriter

    expects_error = """```python
\"\"\"FaultForge scenario: garbled response raises a clear error\"\"\"
import httpx
import pytest
from faultkit import FakeAPI, FaultyTransport, Malformed

from orders.service import OrderService


def test_garbled_response_raises():
    http = httpx.Client(transport=FaultyTransport(FakeAPI(), Malformed(on_calls={1})))
    service = OrderService(FulfillmentClient(http, base_url="https://f.test"))
    with pytest.raises(Exception):
        service.place_order("c", [])
```"""
    plan = json.dumps({"scenarios": [{"fault": "malformed", "invariant": "clear error"}]})
    events = EventLog()
    writer = ScenarioWriter(
        StubLLM(plan=[plan], write=[expects_error]), ORDER_SERVICE_REPO, DEPENDENCY, "", events
    )

    with LocalSandbox() as sandbox:
        kept = validate_scenarios(writer, sandbox, ORDER_SERVICE_REPO, writer.write_all(), events)

    assert [s.fault for s in kept] == ["malformed"]


def test_an_exception_raised_inside_application_code_is_a_genuine_failure():
    from faultforge.replay import Check, Outcome
    from faultforge.scenarios import scenario_is_broken

    output = (
        "tests/test_ff_x.py:12: in test_x\n    service.place_order()\n"
        "orders/fulfillment.py:20: in create_fulfillment\n    return response.json()\n"
        "E   json.decoder.JSONDecodeError: Unterminated string\n"
    )
    check = Check(
        "x", Outcome.FAILED, "json.decoder.JSONDecodeError: Unterminated string", "s", 0.1, output
    )

    assert not scenario_is_broken(check, "tests/test_ff_x.py")


def test_an_exception_raised_in_the_test_file_itself_is_a_test_bug():
    from faultforge.replay import Check, Outcome
    from faultforge.scenarios import scenario_is_broken

    output = (
        "tests/test_ff_x.py:30: in test_x\n    assert fake.accepted[0]['id']\nE   KeyError: 'id'\n"
    )
    check = Check("x", Outcome.FAILED, "KeyError: 'id'", "s", 0.1, output)

    assert scenario_is_broken(check, "tests/test_ff_x.py")


def test_a_fault_dependent_assertion_is_never_treated_as_a_test_bug():
    from faultforge.replay import Check, Outcome
    from faultforge.scenarios import scenario_is_broken

    output = (
        "tests/test_ff_x.py:30: in test_x\n    assert not paid\nE   AssertionError: marked paid\n"
    )
    check = Check("x", Outcome.FAILED, "AssertionError: marked paid", "s", 0.1, output)

    assert not scenario_is_broken(check, "tests/test_ff_x.py")


TRIAGE_BUG = json.dumps({"verdict": "application_bug", "reason": "retry without idempotency"})
TRIAGE_MISTAKE = json.dumps(
    {"verdict": "test_mistake", "reason": "the test reads an order it never created"}
)


def test_triage_sends_a_test_mistake_back_to_the_writer_with_the_reason():
    from faultforge.auto import validate_scenarios
    from faultforge.scenarios import ScenarioWriter

    plan = json.dumps({"scenarios": [{"fault": "timeout", "invariant": "one fulfillment"}]})
    events = EventLog()
    writer = ScenarioWriter(
        StubLLM(plan=[plan, TRIAGE_MISTAKE, TRIAGE_BUG], write=[GOOD_FILL, GOOD_FILL]),
        ORDER_SERVICE_REPO,
        DEPENDENCY,
        "",
        events,
    )

    with LocalSandbox() as sandbox:
        kept = validate_scenarios(writer, sandbox, ORDER_SERVICE_REPO, writer.write_all(), events)

    assert [s.fault for s in kept] == ["timeout"]
    assert any(
        e.type == "scenario_triaged" and e.data["verdict"] == "test_mistake" for e in events.items()
    )
    assert "reads an order it never created" in writer.llm.calls[-2].user


# Seen live on 2026-10-17: triage called the duplicate-order test a mistake ("the retry
# inevitably creates a second"), and the rewrite asserted the bug instead of the invariant.
INVERTED_FILL = GOOD_FILL.replace(
    "assert len(dependency.accepted) == 1", "assert len(dependency.accepted) == 2"
)


def test_a_triaged_rewrite_that_passes_on_the_original_code_is_dropped():
    from faultforge.auto import validate_scenarios
    from faultforge.scenarios import ScenarioWriter

    plan = json.dumps({"scenarios": [{"fault": "timeout", "invariant": "one fulfillment"}]})
    events = EventLog()
    writer = ScenarioWriter(
        StubLLM(plan=[plan, TRIAGE_MISTAKE], write=[GOOD_FILL, INVERTED_FILL]),
        ORDER_SERVICE_REPO,
        DEPENDENCY,
        "",
        events,
    )

    with LocalSandbox() as sandbox:
        kept = validate_scenarios(writer, sandbox, ORDER_SERVICE_REPO, writer.write_all(), events)

    assert kept == []
    discarded = [e for e in events.items() if e.type == "scenario_discarded"]
    assert "no longer fails" in discarded[-1].data["reason"]


def test_triage_keeps_an_application_bug():
    from faultforge.auto import validate_scenarios
    from faultforge.scenarios import ScenarioWriter

    plan = json.dumps({"scenarios": [{"fault": "timeout", "invariant": "one fulfillment"}]})
    events = EventLog()
    writer = ScenarioWriter(
        StubLLM(plan=[plan, TRIAGE_BUG], write=[GOOD_FILL]),
        ORDER_SERVICE_REPO,
        DEPENDENCY,
        "",
        events,
    )

    with LocalSandbox() as sandbox:
        kept = validate_scenarios(writer, sandbox, ORDER_SERVICE_REPO, writer.write_all(), events)

    assert [s.fault for s in kept] == ["timeout"]
    assert len([c for c in writer.llm.calls if c.role == "fix"]) == 0


def test_validation_runs_are_labelled_separately_from_the_baseline():
    from faultforge.auto import validate_scenarios
    from faultforge.scenarios import ScenarioWriter

    plan = json.dumps({"scenarios": [{"fault": "timeout", "invariant": "one fulfillment"}]})
    events = EventLog()
    writer = ScenarioWriter(
        StubLLM(plan=[plan, TRIAGE_BUG], write=[GOOD_FILL]),
        ORDER_SERVICE_REPO,
        DEPENDENCY,
        "",
        events,
    )

    with LocalSandbox() as sandbox:
        validate_scenarios(writer, sandbox, ORDER_SERVICE_REPO, writer.write_all(), events)

    branches = {e.data["branch"] for e in events.items() if e.type == "run_finished"}
    assert branches == {"validation"}
