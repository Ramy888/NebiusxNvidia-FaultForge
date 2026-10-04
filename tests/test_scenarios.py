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
    assert fixed and "NameError" in writer.llm.calls[-1].user
    assert {s.fault for s in kept} == {"timeout", "malformed"}
