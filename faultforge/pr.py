"""Turn the winning repair into a pull request: the patch, the regression test, the evidence."""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .pipeline import PipelineResult
from .report import render_markdown
from .sandbox import safe_relative_path
from .workspace import faultkit_files


class PullRequestError(Exception):
    pass


@dataclass(frozen=True)
class PullRequestPlan:
    branch: str
    title: str
    body: str
    files: dict[str, str]
    # The regression test imports the fault kit, so it ships with the PR.
    support_files: dict[str, str] = field(default_factory=dict)


def plan_pull_request(result: PipelineResult, found=None) -> PullRequestPlan:
    winner = result.winner
    if winner is None:
        raise PullRequestError("no verified repair to propose")
    fixed = [s for s in result.scenarios if s.id in winner.fixed]
    faults = sorted({s.fault.replace("_", " ") for s in fixed})
    return PullRequestPlan(
        branch=f"faultforge/{winner.candidate.id}",
        title=f"Fix {' and '.join(faults)} failure: {winner.candidate.summary}"[:120],
        body=render_markdown(result, found)
        + "\n---\nOpened by FaultForge. The regression tests keep these failures fixed.\n",
        # Regression tests only for the failures this patch actually fixes.
        files=winner.candidate.files | {s.test_path: s.test_code for s in fixed},
        support_files=faultkit_files(),
    )


def open_pull_request(
    plan: PullRequestPlan,
    repo_dir: Path,
    runner: Callable = subprocess.run,
    dry_run: bool = True,
) -> dict:
    preview = {
        "dry_run": dry_run,
        "branch": plan.branch,
        "title": plan.title,
        "body": plan.body,
        "files": sorted(plan.files | plan.support_files),
    }
    if dry_run:
        return preview

    def git(*args: str) -> subprocess.CompletedProcess:
        done = runner(list(args), cwd=repo_dir, capture_output=True, text=True)
        if done.returncode != 0:
            raise PullRequestError(f"{' '.join(args[:3])} failed: {done.stderr.strip()}")
        return done

    git("git", "switch", "-c", plan.branch)
    for path, content in (plan.files | plan.support_files).items():
        target = repo_dir / safe_relative_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    git("git", "add", "--", *sorted(plan.files | plan.support_files))
    git("git", "commit", "-m", plan.title)
    git("git", "push", "-u", "origin", plan.branch)
    created = git("gh", "pr", "create", "--title", plan.title, "--body", plan.body)
    return preview | {"url": created.stdout.strip().splitlines()[-1]}
