"""Re-triage: when every patch that made a test pass changed only code off the dependency path,
the test most likely assumes something the app never promised. It goes back to the writer."""

import json

from faultforge.demo import ORDER_SERVICE_REPO
from faultforge.discovery import CallSite, Dependency
from faultforge.events import EventLog
from faultforge.llm import StubLLM
from faultforge.models import Candidate, Scenario
from faultforge.pipeline import Status, run_pipeline, suspect_scenarios
from faultforge.replay import CandidateResult as Result
from faultforge.replay import Check, Outcome
from faultforge.sandbox import LocalSandbox
from faultforge.serialize import result_to_dict

ORDERS = Dependency(
    name="Fulfillment Provider API",
    operation="orders.service:OrderService.place_order",
    notes="",
    call_sites=[
        CallSite("orders/fulfillment.py", 1, "FulfillmentClient.create_fulfillment", "post", "")
    ],
)


def result(cid: str, fixed: list[str], off_path: list[str], on_path_changed: bool, reason=""):
    ok = Check("existing_tests", Outcome.PASSED, "", "snap", 0.0, "")
    return Result(
        existing_tests=ok,
        scenarios={},
        candidate=Candidate(cid, cid),
        diff="",
        diff_lines=1,
        fixed=fixed,
        rejection_reason=reason or ("changes code off the dependency path" if off_path else ""),
        off_path=off_path,
        on_path_changed=on_path_changed,
    )


# --- which tests are suspect ---------------------------------------------------------------------


def test_a_test_only_off_path_patches_could_satisfy_is_suspect():
    results = [result("hack", ["x"], ["m.py:Book.status"], on_path_changed=False)]

    assert suspect_scenarios(results, ["x"]) == (["x"], [])


def test_a_mixed_patch_is_only_a_possible_test_mistake():
    # the documented 2026-10-06 patch: a real fix plus the hack, in one candidate
    results = [result("mixed", ["rate", "x"], ["m.py:Book.status"], on_path_changed=True)]

    assert suspect_scenarios(results, ["rate", "x"]) == ([], ["rate", "x"])


def test_one_on_path_fixer_clears_the_test():
    results = [
        result("hack", ["x"], ["m.py:Book.status"], on_path_changed=False),
        result("real", ["x"], [], on_path_changed=True, reason="regresses scenarios: y"),
    ]

    assert suspect_scenarios(results, ["x"]) == ([], [])


def test_a_test_nothing_fixed_is_not_suspect():
    results = [result("other", ["y"], ["m.py:f"], on_path_changed=False)]

    assert suspect_scenarios(results, ["x"]) == ([], [])


# --- end to end ----------------------------------------------------------------------------------

SENTINEL = Scenario(
    id="sentinel",
    title="listing orders shows the sentinel",
    fault="timeout",
    test_code=(
        "from orders.service import OrderService\n\n\n"
        "def test_listing():\n"
        '    assert OrderService(None).list_orders() == ["sentinel"]\n'
    ),
)
CORRECTED = Scenario(
    id="sentinel",
    title="a new service lists no orders",
    fault="timeout",
    test_code=(
        "from orders.service import OrderService\n\n\n"
        "def test_listing():\n"
        "    assert OrderService(None).list_orders() == []\n"
    ),
)


def stub() -> StubLLM:
    service = (ORDER_SERVICE_REPO / "orders" / "service.py").read_text()
    hacked = service.replace("return list(self._orders)", 'return ["sentinel"]')
    assert hacked != service
    plan = {"strategies": [{"id": "sentinel", "summary": "List the sentinel", "approach": "x"}]}
    return StubLLM(
        plan=[json.dumps(plan)], write=[json.dumps({"files": {"orders/service.py": hacked}})]
    )


def run(retriage, events: EventLog | None = None):
    with LocalSandbox() as sandbox:
        return run_pipeline(
            ORDER_SERVICE_REPO,
            [SENTINEL],
            stub(),
            sandbox,
            events or EventLog(),
            dependency=ORDERS,
            retriage=retriage,
        )


def test_suspect_test_goes_back_to_the_writer_and_the_run_is_redone():
    calls = []

    def retriage(scenario, evidence):
        calls.append((scenario.id, evidence))
        return CORRECTED

    events = EventLog()
    outcome = run(retriage, events)

    assert [c[0] for c in calls] == ["sentinel"]
    assert "OrderService.list_orders" in calls[0][1]
    assert outcome.status is Status.NO_FAILURE  # the corrected test passes: it was the test's fault
    assert outcome.retriaged == ["sentinel"]
    triaged = [e.data for e in events.items() if e.type == "scenario_triaged"]
    assert triaged and triaged[-1]["verdict"] == "test_mistake"


def test_without_a_writer_the_suspect_is_reported():
    outcome = run(None)

    assert outcome.status is Status.NO_REPAIR
    assert outcome.suspects == ["sentinel"]
    assert result_to_dict(outcome)["suspect_tests"] == ["sentinel"]
    assert "probably a mistake in the test" in result_to_dict(outcome)["markdown"]


def test_a_writer_that_cannot_fix_it_leaves_the_suspect_reported():
    outcome = run(lambda scenario, evidence: None)

    assert outcome.status is Status.NO_REPAIR
    assert outcome.suspects == ["sentinel"]
    assert outcome.retriaged == []
