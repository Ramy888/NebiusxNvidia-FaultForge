"""Run every scenario against the baseline and against each candidate repair, then rank."""

import difflib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .events import EventLog
from .models import Candidate, Scenario
from .sandbox import RunResult, Sandbox, Snapshot
from .scope import off_path_changes

# `python -m pytest` (not the `pytest` script) puts the repo root on sys.path, which is what lets
# scenario tests `import faultkit` and the app's own packages without any packaging step.
PYTEST = "python -m pytest -q --tb=short -rfE -p no:cacheprovider"
EXISTING_TESTS = f"{PYTEST} --ignore-glob='*/test_ff_*.py'"
CHECK_TIMEOUT_S = 120
NO_TESTS_COLLECTED = 5  # pytest exit code
OUTPUT_TAIL_CHARS = 4000


class Outcome(Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    TIMED_OUT = "timed_out"


@dataclass
class Check:
    name: str
    outcome: Outcome
    message: str
    snapshot_id: str
    duration_s: float
    output: str


@dataclass
class Branch:
    existing_tests: Check
    scenarios: dict[str, Check]


@dataclass
class CandidateResult(Branch):
    candidate: Candidate = None
    diff: str = ""
    diff_lines: int = 0
    fixed: list[str] = field(default_factory=list)
    regressed: list[str] = field(default_factory=list)
    rejection_reason: str = ""

    @property
    def accepted(self) -> bool:
        return not self.rejection_reason


@dataclass
class ReplayReport:
    baseline: Branch
    results: list[CandidateResult]

    @property
    def ranking(self) -> list[CandidateResult]:
        return sorted(self.results, key=lambda r: (not r.accepted, -len(r.fixed), r.diff_lines))

    def result_for(self, candidate_id: str) -> CandidateResult:
        return next(r for r in self.results if r.candidate.id == candidate_id)


def classify(result: RunResult) -> tuple[Outcome, str]:
    output = result.stdout + result.stderr
    if result.timed_out:
        return Outcome.TIMED_OUT, "timed out"
    if result.exit_code == 0:
        return Outcome.PASSED, ""
    lines = output.splitlines()
    errors = [line[1:].strip() for line in lines if line.startswith("E ")]
    summary = [line for line in lines if line.startswith(("FAILED ", "ERROR "))]
    message = errors[0] if errors else summary[0] if summary else output.strip()[-300:]
    outcome = Outcome.FAILED if result.exit_code == 1 else Outcome.ERROR
    return outcome, message


def unified_diff(source: Path, files: dict[str, str]) -> tuple[str, int]:
    chunks, changed = [], 0
    for path, new in sorted(files.items()):
        original_file = source / path
        old = original_file.read_text() if original_file.exists() else ""
        before, after = old.splitlines(keepends=True), new.splitlines(keepends=True)
        lines = list(difflib.unified_diff(before, after, f"a/{path}", f"b/{path}"))
        changed += sum(
            1 for line in lines if line[:1] in "+-" and not line.startswith(("+++", "---"))
        )
        chunks.append("".join(lines))
    return "".join(chunks), changed


class _Runner:
    """Runs the existing suite and every scenario as parallel branches from one snapshot."""

    def __init__(self, sandbox: Sandbox, scenarios: list[Scenario], events: EventLog, pool):
        self.sandbox, self.scenarios, self.events, self.pool = sandbox, scenarios, events, pool

    def check(self, snapshot: Snapshot, branch: str, name: str, command: str) -> Check:
        self.events.emit("run_started", branch=branch, check=name, snapshot=snapshot.id)
        result = self.sandbox.run(snapshot, command, timeout=CHECK_TIMEOUT_S)
        outcome, message = classify(result)
        if name == "existing_tests" and result.exit_code == NO_TESTS_COLLECTED:
            outcome, message = Outcome.PASSED, "the repo has no tests of its own"
        self.events.emit(
            "run_finished",
            branch=branch,
            check=name,
            outcome=outcome.value,
            message=message,
            snapshot=result.snapshot.id,
            duration_s=round(result.duration_s, 3),
        )
        output = (result.stdout + result.stderr)[-OUTPUT_TAIL_CHARS:]
        return Check(name, outcome, message, result.snapshot.id, result.duration_s, output)

    def branch(self, snapshot: Snapshot, branch: str) -> Branch:
        existing = self.pool.submit(self.check, snapshot, branch, "existing_tests", EXISTING_TESTS)
        per_scenario = {
            s.id: self.pool.submit(self.check, snapshot, branch, s.id, f"{PYTEST} {s.test_path}")
            for s in self.scenarios
        }
        return Branch(existing.result(), {k: f.result() for k, f in per_scenario.items()})


def run_baseline(
    sandbox: Sandbox,
    base: Snapshot,
    scenarios: list[Scenario],
    events: EventLog,
    max_workers: int = 4,
    label: str = "baseline",
) -> Branch:
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return _Runner(sandbox, scenarios, events, pool).branch(base, label)


def replay(
    sandbox: Sandbox,
    base: Snapshot,
    source: Path,
    scenarios: list[Scenario],
    candidates: list[Candidate],
    events: EventLog,
    max_workers: int = 4,
    baseline: Branch | None = None,
    target: str | None = None,
    dependency=None,
) -> ReplayReport:
    events.emit(
        "replay_started",
        base=base.id,
        scenarios=[s.id for s in scenarios],
        candidates=[c.id for c in candidates],
    )
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        runner = _Runner(sandbox, scenarios, events, pool)
        if baseline is None:
            baseline = runner.branch(base, "baseline")
        results = [
            _evaluate(sandbox, base, source, c, baseline, runner.branch, events, target, dependency)
            for c in candidates
        ]

    report = ReplayReport(baseline, results)
    events.emit("replay_finished", ranking=[r.candidate.id for r in report.ranking])
    return report


def judge(
    before: dict[str, Outcome],
    after: dict[str, Outcome],
    existing: Outcome,
    target: str | None = None,
) -> tuple[str, list[str], list[str]]:
    """Returns (rejection reason or "", fixed scenarios, regressed scenarios)."""
    fixed = [k for k in after if before[k] is not Outcome.PASSED and after[k] is Outcome.PASSED]
    regressed = [k for k in after if before[k] is Outcome.PASSED and after[k] is not Outcome.PASSED]
    if existing is not Outcome.PASSED:
        reason = "breaks existing tests"
    elif regressed:
        reason = f"regresses scenarios: {', '.join(regressed)}"
    elif not fixed:
        reason = "fixes no failing scenario"
    elif target is not None and target not in fixed:
        reason = f"does not fix {target}"
    else:
        reason = ""
    return reason, fixed, regressed


def _evaluate(
    sandbox, base, source, candidate, baseline, run_branch, events, target=None, dependency=None
) -> CandidateResult:
    applied = sandbox.run(base, "true", files=candidate.files, timeout=60)
    diff, diff_lines = unified_diff(source, candidate.files)
    if applied.exit_code != 0 or applied.timed_out:
        events.emit("candidate_rejected", candidate=candidate.id, reason="patch not applied")
        return CandidateResult(
            existing_tests=baseline.existing_tests,
            scenarios=baseline.scenarios,
            candidate=candidate,
            diff=diff,
            diff_lines=diff_lines,
            rejection_reason="patch could not be applied in the sandbox",
        )
    events.emit(
        "candidate_applied",
        candidate=candidate.id,
        summary=candidate.summary,
        parent=base.id,
        snapshot=applied.snapshot.id,
        diff=diff,
    )
    branch = run_branch(applied.snapshot, candidate.id)
    reason, fixed, regressed = judge(
        {k: c.outcome for k, c in baseline.scenarios.items()},
        {k: c.outcome for k, c in branch.scenarios.items()},
        branch.existing_tests.outcome,
        target,
    )
    if not reason and dependency is not None:
        reason = _off_path_reason(source, candidate, dependency)
    return CandidateResult(
        existing_tests=branch.existing_tests,
        scenarios=branch.scenarios,
        candidate=candidate,
        diff=diff,
        diff_lines=diff_lines,
        fixed=fixed,
        regressed=regressed,
        rejection_reason=reason,
    )


def _off_path_reason(source: Path, candidate: Candidate, dependency) -> str:
    """Green checks are not enough: a repair that changes code the dependency path never reaches
    is usually bending the app to fit a mistaken test (see scope.py)."""
    original = {p: (source / p).read_text() for p in candidate.files if (source / p).is_file()}
    off_path = off_path_changes(original, candidate.files, dependency, source)
    if not off_path:
        return ""
    return (
        f"changes code off the dependency path ({', '.join(off_path)}); a repair should change how "
        f"the app handles {dependency.name}, not code that only a test uses"
    )
