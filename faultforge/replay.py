"""Run every scenario against the baseline and against each candidate repair, then rank."""

import difflib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .events import EventLog
from .models import Candidate, Scenario
from .sandbox import RunResult, Sandbox, Snapshot

PYTEST = "python -m pytest -q --tb=short -rfE -p no:cacheprovider"
EXISTING_TESTS = f"{PYTEST} --ignore-glob='*/test_ff_*.py'"
CHECK_TIMEOUT_S = 120
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


def replay(
    sandbox: Sandbox,
    base: Snapshot,
    source: Path,
    scenarios: list[Scenario],
    candidates: list[Candidate],
    events: EventLog,
    max_workers: int = 4,
) -> ReplayReport:
    events.emit(
        "replay_started",
        base=base.id,
        scenarios=[s.id for s in scenarios],
        candidates=[c.id for c in candidates],
    )
    with ThreadPoolExecutor(max_workers=max_workers) as pool:

        def check(snapshot: Snapshot, branch: str, name: str, command: str) -> Check:
            events.emit("run_started", branch=branch, check=name, snapshot=snapshot.id)
            result = sandbox.run(snapshot, command, timeout=CHECK_TIMEOUT_S)
            outcome, message = classify(result)
            events.emit(
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

        def run_branch(snapshot: Snapshot, branch: str) -> Branch:
            existing = pool.submit(check, snapshot, branch, "existing_tests", EXISTING_TESTS)
            per_scenario = {
                s.id: pool.submit(check, snapshot, branch, s.id, f"{PYTEST} {s.test_path}")
                for s in scenarios
            }
            return Branch(existing.result(), {k: f.result() for k, f in per_scenario.items()})

        baseline = run_branch(base, "baseline")
        results = [
            _evaluate(sandbox, base, source, c, baseline, run_branch, events) for c in candidates
        ]

    report = ReplayReport(baseline, results)
    events.emit("replay_finished", ranking=[r.candidate.id for r in report.ranking])
    return report


def _evaluate(sandbox, base, source, candidate, baseline, run_branch, events) -> CandidateResult:
    applied = sandbox.run(base, "true", files=candidate.files, timeout=60)
    diff, diff_lines = unified_diff(source, candidate.files)
    events.emit(
        "candidate_applied",
        candidate=candidate.id,
        summary=candidate.summary,
        parent=base.id,
        snapshot=applied.snapshot.id,
        diff=diff,
    )
    branch = run_branch(applied.snapshot, candidate.id)
    before = {k: c.outcome for k, c in baseline.scenarios.items()}
    after = {k: c.outcome for k, c in branch.scenarios.items()}
    fixed = [k for k in after if before[k] is not Outcome.PASSED and after[k] is Outcome.PASSED]
    regressed = [k for k in after if before[k] is Outcome.PASSED and after[k] is not Outcome.PASSED]
    if branch.existing_tests.outcome is not Outcome.PASSED:
        reason = "breaks existing tests"
    elif regressed:
        reason = f"regresses scenarios: {', '.join(regressed)}"
    elif not fixed:
        reason = "fixes no failing scenario"
    else:
        reason = ""
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
