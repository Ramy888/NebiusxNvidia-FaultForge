"""Regression tests for issues found in code review of the first build."""

import json
from pathlib import Path

from faultforge.events import EventLog
from faultforge.faultkit import FakeAPI, FaultyTransport
from faultforge.llm import StubLLM
from faultforge.models import Candidate, Scenario
from faultforge.pipeline import Status, run_pipeline
from faultforge.repair import generate_repairs
from faultforge.replay import Outcome, judge, replay
from faultforge.sandbox import LocalSandbox, RunResult
from faultforge.workspace import prepare_workspace

F, P = Outcome.FAILED, Outcome.PASSED


def test_a_repair_must_fix_the_target_scenario_not_just_any():
    reason, fixed, _ = judge(
        before={"target": F, "other": F},
        after={"target": F, "other": P},
        existing=P,
        target="target",
    )

    assert fixed == ["other"]
    assert "does not fix target" in reason


def test_a_repair_fixing_the_target_is_accepted():
    reason, _, _ = judge(before={"t": F}, after={"t": P}, existing=P, target="t")

    assert reason == ""


def test_repo_without_tests_of_its_own_has_a_passing_baseline(tmp_path: Path):
    (tmp_path / "app.py").write_text("def ok():\n    return True\n")
    scenario = Scenario("s", "always fails", "timeout", "def test_s():\n    assert False, 'boom'\n")
    events = EventLog()

    with LocalSandbox() as sandbox:
        result = run_pipeline(tmp_path, [scenario], StubLLM(), sandbox, events)

    assert result.baseline.existing_tests.outcome is Outcome.PASSED
    assert result.status is not Status.BROKEN_BASELINE


def test_when_every_scenario_is_discarded_the_status_says_so(tmp_path: Path):
    (tmp_path / "app.py").write_text("X = 1\n")
    broken = Scenario("b", "buggy test", "timeout", "def test_b():\n    undefined_name()\n")

    with LocalSandbox() as sandbox:
        result = run_pipeline(tmp_path, [broken], StubLLM(), sandbox, EventLog())

    assert result.status is Status.NO_VALID_SCENARIOS


class FailingApplySandbox(LocalSandbox):
    def run(self, snapshot, command, files=None, timeout=120):
        if command == "true" and files and "app.py" in files:
            return RunResult(snapshot, -9, "", "timed out", True, 60.0)
        return super().run(snapshot, command, files, timeout)


def test_a_patch_that_cannot_be_applied_is_rejected_as_such(tmp_path: Path):
    (tmp_path / "app.py").write_text("X = 1\n")
    scenario = Scenario("s", "fails", "timeout", "def test_s():\n    assert False, 'x'\n")
    with FailingApplySandbox() as sandbox:
        base = prepare_workspace(sandbox, tmp_path, [scenario])
        report = replay(
            sandbox,
            base,
            tmp_path,
            [scenario],
            [Candidate("c", "c", {"app.py": "X = 2\n"})],
            EventLog(),
        )

    assert "could not be applied" in report.result_for("c").rejection_reason


def test_a_model_error_on_one_strategy_keeps_the_candidates_already_written():
    plan = json.dumps({"strategies": [{"id": "a", "summary": "A"}, {"id": "b", "summary": "B"}]})
    llm = StubLLM(plan=[plan], write=[json.dumps({"files": {"orders/a.py": "x = 1\n"}})])
    scenario = Scenario("s", "t", "timeout", "def test(): pass\n")
    source = Path(__file__).resolve().parents[1] / "examples" / "order-service"

    candidates = generate_repairs(llm, source, scenario, "boom", EventLog())

    assert [c.id for c in candidates] == ["a"]


def test_repairs_may_not_change_test_configuration():
    plan = json.dumps({"strategies": [{"id": "a", "summary": "A"}]})
    sneaky = json.dumps({"files": {"conftest.py": "collect_ignore_glob = ['*']\n"}})
    for path in ["conftest.py", "orders/conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg"]:
        sneaky = json.dumps({"files": {path: "x"}})
        llm = StubLLM(plan=[plan], write=[sneaky, sneaky])
        source = Path(__file__).resolve().parents[1] / "examples" / "order-service"

        assert (
            generate_repairs(llm, source, Scenario("s", "t", "timeout", ""), "f", EventLog()) == []
        )


def test_fake_api_accepts_non_json_request_bodies():
    import httpx

    api = FakeAPI()
    http = httpx.Client(transport=FaultyTransport(api))

    http.post("https://dep.test/form", data={"a": "1"})

    assert api.accepted == ["a=1"]


def test_malformed_model_lists_do_not_crash_discovery_or_generation(tmp_path: Path):
    from faultforge.discovery import CallSite, Dependency, discover
    from faultforge.scenarios import generate_scenarios

    (tmp_path / "app.py").write_text(
        "import httpx\n\ndef ping(client):\n    return client.get('https://x.test')\n"
    )
    assert (
        discover(StubLLM(plan=[json.dumps({"dependencies": ["nope", 3]})]), tmp_path, EventLog())
        == []
    )
    dep = Dependency("d", "app:ping", "", [CallSite("app.py", 4, "ping", "get", "")])
    llm = StubLLM(plan=[json.dumps({"scenarios": "timeout"})])
    assert generate_scenarios(llm, tmp_path, dep, "", EventLog()) == []


def test_a_file_with_a_syntax_error_does_not_stop_discovery(tmp_path: Path):
    from faultforge.discovery import find_http_call_sites

    (tmp_path / "legacy.py").write_text("print 'python 2'\n")
    (tmp_path / "app.py").write_text(
        "import httpx\n\ndef ping():\n    return httpx.get('https://x.test')\n"
    )

    assert [s.function for s in find_http_call_sites(tmp_path)] == ["ping"]


def test_pytest_is_a_runtime_dependency():
    """The local sandbox runs `python -m pytest` with FaultForge's own interpreter, so a
    production install (no dev group, e.g. the Docker image) must include pytest."""
    import tomllib

    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    names = [dep.split(">")[0].split("=")[0].strip() for dep in project["project"]["dependencies"]]

    assert "pytest" in names


def test_misusing_the_fault_kit_counts_as_a_test_bug_not_an_app_failure():
    from faultforge.scenarios import is_test_bug

    assert is_test_bug("TypeError: FakeAPI.__init__() got an unexpected keyword argument 'headers'")
    assert is_test_bug("TypeError: FaultyTransport.__init__() takes 2 positional arguments")
    assert not is_test_bug("TypeError: 'NoneType' object is not subscriptable")


def test_cli_can_dump_everything_for_debugging(tmp_path):
    from faultforge.cli import main

    dump = tmp_path / "run.json"

    assert main(["demo", "--dump", str(dump)]) == 0
    data = json.loads(dump.read_text())
    assert data["result"]["scenarios"][0]["test_code"]
    assert any(e["type"] == "candidate_applied" for e in data["events"])


# --- Live-run findings (2026-10-04) -----------------------------------------------------------


def test_misusing_httpx_or_the_fault_kit_by_attribute_is_a_test_bug():
    from faultforge.scenarios import is_test_bug

    assert is_test_bug("AttributeError: module 'httpx' has no attribute 'ResponseError'")
    assert not is_test_bug("AttributeError: 'NoneType' object has no attribute 'status'")


def _order_pipeline(llm, scenarios):
    from faultforge.demo import ORDER_SERVICE_REPO

    events = EventLog()
    with LocalSandbox() as sandbox:
        result = run_pipeline(ORDER_SERVICE_REPO, scenarios, llm, sandbox, events)
    return result, events


def _demo_scenarios():
    from faultforge.demo import ORDER_SERVICE
    from faultforge.scenarios import scenario_from_file

    timeout = scenario_from_file(ORDER_SERVICE / "scenarios" / "timeout_duplicate.py")
    unrelated = Scenario(
        "aaa_unfixable", "always broken", "rate_limit", "def test_x():\n    assert False, 'nope'\n"
    )
    return [unrelated, timeout]  # the unfixable one comes first and becomes the "target"


def _fixture(name: str) -> str:
    return (Path(__file__).parent / "fixtures" / "candidates" / name).read_text()


def test_a_repair_that_fixes_any_reproduced_failure_wins_and_its_pr_carries_those_tests():
    from faultforge.pr import plan_pull_request

    plan = json.dumps({"strategies": [{"id": "idem", "summary": "Idempotency key"}]})
    good = f"### orders/fulfillment.py\n```python\n{_fixture('idempotency_key__fulfillment.py')}```"
    result, _ = _order_pipeline(StubLLM(plan=[plan], write=[good]), _demo_scenarios())

    assert result.status is Status.REPAIRED
    pr = plan_pull_request(result)
    assert "tests/test_ff_timeout_duplicate.py" in pr.files
    assert "tests/test_ff_aaa_unfixable.py" not in pr.files


def test_a_rejected_repair_is_revised_once_with_the_verification_result():
    plan = json.dumps({"strategies": [{"id": "idem", "summary": "Idempotency key"}]})
    breaks = (
        f"### orders/fulfillment.py\n```python\n{_fixture('breaks_contract__fulfillment.py')}```"
    )
    good = f"### orders/fulfillment.py\n```python\n{_fixture('idempotency_key__fulfillment.py')}```"
    llm = StubLLM(plan=[plan], write=[breaks, good])

    result, events = _order_pipeline(llm, _demo_scenarios()[1:])

    assert result.status is Status.REPAIRED
    assert result.winner.candidate.id == "idem_revised"
    assert any(e.type == "candidate_revised" for e in events.items())
    assert "Existing test suite: failed" in llm.calls[-1].user
