from pathlib import Path

import pytest

from faultforge.events import EventLog
from faultforge.models import Candidate, Scenario
from faultforge.replay import Outcome, replay
from faultforge.sandbox import LocalSandbox
from faultforge.workspace import prepare_workspace

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "order-service"
CANDIDATES = ROOT / "tests" / "fixtures" / "candidates"


def fixture_candidate(name: str, target: str) -> Candidate:
    content = (CANDIDATES / f"{name}__{Path(target).name}").read_text()
    return Candidate(id=name, summary=name.replace("_", " "), files={target: content})


TIMEOUT_SCENARIO = Scenario(
    id="timeout_duplicate",
    title="Provider accepts the order but the response times out",
    fault="timeout",
    test_code=(ROOT / "tests" / "fixtures" / "scenarios" / "timeout_duplicate.py").read_text(),
)
GOOD = fixture_candidate("idempotency_key", "orders/fulfillment.py")
NO_RETRY = fixture_candidate("no_retry", "orders/service.py")
BREAKS = fixture_candidate("breaks_contract", "orders/fulfillment.py")


@pytest.fixture(scope="module")
def report():
    events = EventLog()
    with LocalSandbox() as sandbox:
        base = prepare_workspace(sandbox, EXAMPLE, [TIMEOUT_SCENARIO])
        yield replay(sandbox, base, EXAMPLE, [TIMEOUT_SCENARIO], [NO_RETRY, BREAKS, GOOD], events)


def test_baseline_reproduces_the_failure(report):
    assert report.baseline.scenarios["timeout_duplicate"].outcome is Outcome.FAILED
    assert "2 fulfillments" in report.baseline.scenarios["timeout_duplicate"].message


def test_baseline_existing_tests_pass(report):
    assert report.baseline.existing_tests.outcome is Outcome.PASSED


def test_idempotency_repair_ranks_first(report):
    assert report.ranking[0].candidate.id == "idempotency_key"
    assert report.ranking[0].fixed == ["timeout_duplicate"]
    assert report.ranking[0].accepted


def test_removing_retries_does_not_fix_the_scenario(report):
    no_retry = report.result_for("no_retry")
    assert no_retry.scenarios["timeout_duplicate"].outcome is Outcome.FAILED
    assert not no_retry.accepted


def test_repair_breaking_existing_tests_is_rejected(report):
    broken = report.result_for("breaks_contract")
    assert broken.existing_tests.outcome is Outcome.FAILED
    assert not broken.accepted
    assert "existing tests" in broken.rejection_reason


def test_before_and_after_are_recorded_per_scenario(report):
    good = report.result_for("idempotency_key")
    before = report.baseline.scenarios["timeout_duplicate"].outcome
    after = good.scenarios["timeout_duplicate"].outcome
    assert (before, after) == (Outcome.FAILED, Outcome.PASSED)


def test_diff_is_recorded_for_each_candidate(report):
    good = report.result_for("idempotency_key")
    assert '+            headers={"Idempotency-Key": order_id},' in good.diff
    assert good.diff_lines == 1


def test_replay_emits_events():
    events = EventLog()
    with LocalSandbox() as sandbox:
        base = prepare_workspace(sandbox, EXAMPLE, [TIMEOUT_SCENARIO])
        replay(sandbox, base, EXAMPLE, [TIMEOUT_SCENARIO], [GOOD], events)

    kinds = [event.type for event in events.items()]
    assert kinds[0] == "replay_started"
    assert kinds.count("run_finished") == 4  # baseline: existing + scenario; candidate: same
    assert kinds[-1] == "replay_finished"
