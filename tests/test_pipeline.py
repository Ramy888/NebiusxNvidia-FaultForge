from pathlib import Path

from faultforge.cli import main
from faultforge.demo import ORDER_SERVICE, ORDER_SERVICE_REPO
from faultforge.events import EventLog
from faultforge.llm import StubLLM
from faultforge.models import Scenario
from faultforge.pipeline import Status, load_stub, run_pipeline
from faultforge.report import render_markdown
from faultforge.sandbox import LocalSandbox
from faultforge.scenarios import scenario_from_file

TIMEOUT_FILE = ORDER_SERVICE / "scenarios" / "timeout_duplicate.py"


def run_demo(events: EventLog | None = None):
    with LocalSandbox() as sandbox:
        return run_pipeline(
            ORDER_SERVICE_REPO,
            [scenario_from_file(TIMEOUT_FILE)],
            load_stub(ORDER_SERVICE / "llm_responses.json"),
            sandbox,
            events or EventLog(),
        )


def test_scenario_from_file_reads_title_and_fault():
    scenario = scenario_from_file(TIMEOUT_FILE)

    assert scenario.id == "timeout_duplicate"
    assert scenario.title == "the provider accepts an order but the response times out."
    assert scenario.fault == "timeout"


def test_pipeline_goes_from_reproduced_failure_to_ranked_repair():
    result = run_demo()

    assert result.status is Status.REPAIRED
    assert result.target.id == "timeout_duplicate"
    assert result.winner.candidate.id == "idempotency_key"


def test_pipeline_emits_start_and_finish_events():
    events = EventLog()

    run_demo(events)

    kinds = [e.type for e in events.items()]
    assert kinds[0] == "pipeline_started"
    assert kinds[-1] == "pipeline_finished"
    assert "repairs_planned" in kinds


def test_pipeline_stops_when_no_failure_is_reproduced():
    passing = Scenario(
        id="ok", title="nothing breaks", fault="timeout", test_code="def test_ok():\n    pass\n"
    )

    with LocalSandbox() as sandbox:
        result = run_pipeline(ORDER_SERVICE_REPO, [passing], StubLLM(), sandbox, EventLog())

    assert result.status is Status.NO_FAILURE
    assert result.report is None


def test_report_shows_fault_wrong_result_candidates_and_before_after():
    markdown = render_markdown(run_demo())

    assert "timeout" in markdown
    assert "one order created 2 fulfillments at the provider" in markdown
    assert "idempotency_key" in markdown and "no_retry" in markdown
    assert "failed → passed" in markdown
    assert '+            headers={"Idempotency-Key": order_id},' in markdown


def test_cli_demo_writes_a_report_without_network(tmp_path: Path):
    out = tmp_path / "report.md"

    exit_code = main(["demo", "--out", str(out)])

    assert exit_code == 0
    assert "idempotency_key" in out.read_text()


def test_live_run_without_api_key_explains_what_is_missing(monkeypatch, capsys):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)

    exit_code = main(["run", str(ORDER_SERVICE_REPO), "--scenario", str(TIMEOUT_FILE)])

    assert exit_code == 2
    assert "NEBIUS_API_KEY" in capsys.readouterr().err


def test_run_with_recorded_responses_uses_the_local_sandbox(tmp_path: Path):
    out = tmp_path / "r.md"

    exit_code = main(
        [
            "run",
            str(ORDER_SERVICE_REPO),
            "--scenario",
            str(TIMEOUT_FILE),
            "--stub",
            str(ORDER_SERVICE / "llm_responses.json"),
            "--out",
            str(out),
        ]
    )

    assert exit_code == 0
    assert "accepted" in out.read_text()


def test_unusable_model_output_ends_as_no_repair_not_a_crash():
    events = EventLog()

    with LocalSandbox() as sandbox:
        result = run_pipeline(
            ORDER_SERVICE_REPO,
            [scenario_from_file(TIMEOUT_FILE)],
            StubLLM(plan=["garbage", "more garbage"]),
            sandbox,
            events,
        )

    assert result.status is Status.NO_REPAIR
    assert any(e.type == "repair_failed" for e in events.items())


def test_webhook_demo_catches_unverified_payment_and_repairs_it():
    from faultforge.demo import WEBHOOK_SERVICE, WEBHOOK_SERVICE_REPO

    scenario = scenario_from_file(WEBHOOK_SERVICE / "scenarios" / "rate_limited_verification.py")
    with LocalSandbox() as sandbox:
        result = run_pipeline(
            WEBHOOK_SERVICE_REPO,
            [scenario],
            load_stub(WEBHOOK_SERVICE / "llm_responses.json"),
            sandbox,
            EventLog(),
        )

    assert scenario.fault == "rate_limit"
    assert "never verified" in result.baseline.scenarios[scenario.id].message
    assert result.status is Status.REPAIRED
    assert {r.candidate.id for r in result.report.results if r.accepted} == {
        "verify_or_fail",
        "unknown_default",
    }


def test_cli_demo_can_run_the_webhook_example(tmp_path: Path):
    out = tmp_path / "report.md"

    assert main(["demo", "--example", "webhook-service", "--out", str(out)]) == 0
    assert "never verified" in out.read_text()


def test_cli_pr_preview_prints_branch_and_files(capsys):
    assert main(["demo", "--pr-preview"]) == 0

    err = capsys.readouterr().err
    assert "faultforge/idempotency_key" in err
    assert "tests/test_ff_timeout_duplicate.py" in err


def test_live_cli_refuses_the_local_sandbox_unless_explicitly_allowed(monkeypatch, capsys):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    monkeypatch.delenv("FAULTFORGE_ALLOW_LOCAL_LIVE", raising=False)

    exit_code = main(["run", str(ORDER_SERVICE_REPO), "--sandbox", "local"])

    assert exit_code == 2
    assert "isolated sandbox" in capsys.readouterr().err
