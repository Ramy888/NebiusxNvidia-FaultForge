import subprocess

import pytest

from faultforge.pr import PullRequestError, open_pull_request, plan_pull_request
from tests.test_pipeline import run_demo


@pytest.fixture(scope="module")
def plan():
    return plan_pull_request(run_demo())


def test_plan_contains_the_patch_and_the_regression_test(plan):
    assert set(plan.files) == {"orders/fulfillment.py", "tests/test_ff_timeout_duplicate.py"}
    assert 'headers={"Idempotency-Key": order_id}' in plan.files["orders/fulfillment.py"]


def test_plan_title_branch_and_evidence_body(plan):
    assert plan.branch == "faultforge/idempotency_key"
    assert plan.title.startswith("Fix timeout failure:")
    assert "failed → passed" in plan.body


def test_regression_test_does_not_need_faultforge_installed(plan):
    test_code = plan.files["tests/test_ff_timeout_duplicate.py"]
    assert "from faultkit import" in test_code
    assert "faultkit/__init__.py" in plan.support_files


def test_no_winner_means_no_pull_request():
    from faultforge.pipeline import Status

    result = run_demo()
    result.status = Status.NO_REPAIR
    result.report.results.clear()

    with pytest.raises(PullRequestError):
        plan_pull_request(result)


def test_dry_run_runs_no_commands(plan, tmp_path):
    calls = []

    preview = open_pull_request(plan, tmp_path, runner=lambda *a, **k: calls.append(a))

    assert calls == []
    assert preview["dry_run"] is True
    assert preview["branch"] == "faultforge/idempotency_key"


def test_real_run_branches_commits_pushes_and_opens_the_pr(plan, tmp_path):
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "https://github.com/o/r/pull/7\n", "")

    outcome = open_pull_request(plan, tmp_path, runner=runner, dry_run=False)

    commands = [" ".join(c[:3]) for c in calls]
    assert commands[0] == "git switch -c"
    assert "git push -u" in commands
    assert calls[-1][:3] == ["gh", "pr", "create"]
    assert outcome["url"] == "https://github.com/o/r/pull/7"
    assert (tmp_path / "orders" / "fulfillment.py").exists()
    assert (tmp_path / "faultkit" / "__init__.py").exists()
