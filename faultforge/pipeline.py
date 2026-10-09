"""Reproduce → repair → replayed verification, for one repo."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

from .events import EventLog
from .llm import LLM, LLMError, StubLLM
from .models import Scenario
from .repair import RepairError, generate_repairs, revise_repair
from .replay import Branch, CandidateResult, Outcome, ReplayReport, replay, run_baseline
from .sandbox import Sandbox
from .scenarios import scenario_is_broken
from .workspace import prepare_workspace

Retriage = Callable[[Scenario, str], Scenario | None]


class Status(Enum):
    REPAIRED = "repaired"
    NO_REPAIR = "no_repair"
    NO_FAILURE = "no_failure"
    BROKEN_BASELINE = "broken_baseline"
    NO_VALID_SCENARIOS = "no_valid_scenarios"


@dataclass
class PipelineResult:
    repo: str
    status: Status
    scenarios: list[Scenario]
    baseline: Branch
    target: Scenario | None = None
    report: ReplayReport | None = None
    suspects: list[str] = field(default_factory=list)  # tests only off-path patches satisfied
    possible_test_mistakes: list[str] = field(default_factory=list)
    retriaged: list[str] = field(default_factory=list)  # tests rewritten before the second pass
    first_pass: list[CandidateResult] = field(default_factory=list)  # repairs before the rewrite

    @property
    def winner(self) -> CandidateResult | None:
        if self.report and self.report.ranking and self.report.ranking[0].accepted:
            return self.report.ranking[0]
        return None


def load_stub(path: Path) -> StubLLM:
    recorded = json.loads(path.read_text())
    return StubLLM(plan=recorded["plan"], write=recorded["write"])


def run_pipeline(
    source: Path,
    scenarios: list[Scenario],
    llm: LLM,
    sandbox: Sandbox,
    events: EventLog,
    max_candidates: int = 3,
    max_workers: int = 4,
    setup: str | None = None,
    dependency=None,
    retriage: Retriage | None = None,
) -> PipelineResult:
    """`retriage(scenario, evidence)` rewrites a test that only off-path patches could satisfy;
    it returns the corrected scenario, or None. Without it such tests are only reported."""
    events.emit("pipeline_started", repo=source.name, scenarios=[_describe(s) for s in scenarios])
    attempt = dict(
        source=source,
        llm=llm,
        sandbox=sandbox,
        events=events,
        max_candidates=max_candidates,
        max_workers=max_workers,
        setup=setup,
        dependency=dependency,
    )
    result = _attempt(scenarios, **attempt)
    if result.report is not None:
        failing = [
            s.id
            for s in result.scenarios
            if result.baseline.scenarios[s.id].outcome is Outcome.FAILED
        ]
        result.suspects, result.possible_test_mistakes = suspect_scenarios(
            result.report.results, failing
        )
    if result.winner is None and result.suspects and retriage is not None:
        result = _retriage(result, retriage, attempt, events)

    events.emit(
        "pipeline_finished",
        status=result.status.value,
        winner=result.winner.candidate.id if result.winner else None,
    )
    return result


def suspect_scenarios(
    results: list[CandidateResult], failing: list[str]
) -> tuple[list[str], list[str]]:
    """(tests to send back to the writer, tests to report as possibly mistaken).

    A failing test is suspect when patches made it pass, but every one of them changed code off
    the dependency path (whatever else they were also rejected for). If every such patch changed
    nothing on the path, the test can
    only be satisfied by bending unrelated code: it goes back to the writer. If a patch also
    changed the path, the real fix may be what made it pass, so it is only reported (the
    revision step already tells the model to drop the off-path part).
    """
    suspects, possible = [], []
    for scenario in failing:
        fixers = [r for r in results if scenario in r.fixed]
        if not fixers or any(r.accepted or not r.off_path for r in fixers):
            continue
        if all(not r.on_path_changed for r in fixers):
            suspects.append(scenario)
        else:
            possible.append(scenario)
    return suspects, possible


def _retriage(result: PipelineResult, retriage: Retriage, attempt: dict, events) -> PipelineResult:
    """Rewrite each suspect test once, then reproduce and repair again (no further re-triage)."""
    by_id = {s.id: s for s in result.scenarios}
    rewritten = {}
    for scenario_id in result.suspects:
        fixers = [r for r in result.report.results if scenario_id in r.fixed]
        off_path = sorted({f for r in fixers for f in r.off_path})
        reason = (
            "every repair that made it pass changed code off the dependency path "
            f"({', '.join(off_path)})"
        )
        events.emit("scenario_triaged", scenario=scenario_id, verdict="test_mistake", reason=reason)
        # writer.fix keeps only the last 3000 characters, so the explanation goes last
        failure = result.baseline.scenarios[scenario_id].output[-800:]
        patches = "\n".join(r.diff for r in fixers)[:1200]
        evidence = (
            f"The test's original failure:\n{failure}\n\nThe patches that made it pass:\n"
            f"{patches}\n\nEvery repair that made this test pass had to change application code "
            f"that is not on the dependency path: {', '.join(off_path)}. A real fix for the "
            "dependency failure would not need that, so the test most likely relies on behaviour "
            "the application never promised (for example data it never created)."
        )
        fixed = retriage(by_id[scenario_id], evidence)
        if fixed is not None:
            rewritten[scenario_id] = fixed
    if not rewritten:
        return result
    scenarios = [rewritten.get(s.id, s) for s in result.scenarios]
    second = _attempt(scenarios, suffix="_retest", **attempt)
    second.retriaged = sorted(rewritten)
    second.first_pass = result.report.ranking
    suspects, possible = [], []
    if second.report is not None:
        failing = [
            s.id
            for s in second.scenarios
            if second.baseline.scenarios[s.id].outcome is Outcome.FAILED
        ]
        suspects, possible = suspect_scenarios(second.report.results, failing)
    # unrewritten first-pass suspects still stand; a rewritten test is judged by the second pass
    second.suspects = sorted({*suspects, *(s for s in result.suspects if s not in rewritten)})
    second.possible_test_mistakes = sorted({*possible, *result.possible_test_mistakes})
    return second


def _attempt(
    scenarios: list[Scenario],
    source: Path,
    llm: LLM,
    sandbox: Sandbox,
    events: EventLog,
    max_candidates: int,
    max_workers: int,
    setup: str | None,
    dependency,
    suffix: str = "",
) -> PipelineResult:
    """One pass: workspace, baseline, and repairs for what fails. `suffix` keeps the candidate
    ids of a second pass distinct from the first, so both stay visible in the attempt tree."""
    base = prepare_workspace(sandbox, source, scenarios, setup)
    events.emit("workspace_ready", snapshot=base.id)
    baseline = run_baseline(sandbox, base, scenarios, events, max_workers)
    scenarios = _drop_broken_scenarios(scenarios, baseline, events)
    result = PipelineResult(source.name, Status.NO_FAILURE, scenarios, baseline)

    if baseline.existing_tests.outcome is not Outcome.PASSED:
        result.status = Status.BROKEN_BASELINE
    elif not scenarios:
        result.status = Status.NO_VALID_SCENARIOS
    else:
        failing = [s for s in scenarios if baseline.scenarios[s.id].outcome is Outcome.FAILED]
        if failing:
            result.target = failing[0]
            failure = baseline.scenarios[result.target.id].message
            failures = [(s, baseline.scenarios[s.id].message) for s in failing]
            events.emit("failure_reproduced", scenario=result.target.id, message=failure)
            try:
                candidates = generate_repairs(
                    llm, source, result.target, failure, events, max_candidates, failures
                )
            except (RepairError, LLMError) as error:
                events.emit("repair_failed", reason=str(error))
                candidates = []
            # A repair is accepted if it fixes any reproduced failure without regressions; the
            # pull request then carries the tests for exactly what it fixed.
            result.report = replay(
                sandbox,
                base,
                source,
                scenarios,
                _renamed(candidates, suffix),
                events,
                max_workers,
                baseline,
                dependency=dependency,
            )
            if result.winner is None:
                revised = _revise(llm, source, result, failure, failures, events)
                if revised:
                    second = replay(
                        sandbox,
                        base,
                        source,
                        scenarios,
                        revised,  # ids derive from the renamed candidates already
                        events,
                        max_workers,
                        baseline,
                        dependency=dependency,
                    )
                    result.report.results.extend(second.results)
            result.status = Status.REPAIRED if result.winner else Status.NO_REPAIR
    return result


def _renamed(candidates: list, suffix: str) -> list:
    return [replace(c, id=c.id + suffix) for c in candidates] if suffix else candidates


def _revise(llm, source, result, failure, failures, events) -> list:
    """One revision per rejected candidate, told exactly what verification found."""
    revised = []
    for rejected in result.report.results:
        if rejected.rejection_reason.startswith("regresses"):
            continue
        lines = [f"Verdict: rejected ({rejected.rejection_reason})."]
        lines.append(
            f"Existing test suite: {rejected.existing_tests.outcome.value}"
            + (f" — {rejected.existing_tests.message}" if rejected.existing_tests.message else "")
        )
        for scenario in result.scenarios:
            check = rejected.scenarios.get(scenario.id)
            if check is not None:
                note = f" — {check.message}" if check.message else ""
                lines.append(f"{scenario.title}: {check.outcome.value}{note}")
        try:
            candidate = revise_repair(
                llm,
                source,
                result.target,
                failure,
                rejected.candidate,
                "\n".join(lines),
                events,
                failures,
            )
        except LLMError as error:
            events.emit("repair_failed", reason=str(error))
            break
        if candidate is not None:
            revised.append(candidate)
    return revised


def _drop_broken_scenarios(scenarios: list[Scenario], baseline: Branch, events) -> list[Scenario]:
    """A scenario that errors, or fails because of a bug in the test itself, proves nothing."""
    kept = []
    for scenario in scenarios:
        check = baseline.scenarios[scenario.id]
        if scenario_is_broken(check, scenario.test_path):
            events.emit("scenario_discarded", scenario=scenario.id, reason=check.message)
        else:
            kept.append(scenario)
    return kept


def _describe(scenario: Scenario) -> dict:
    return {"id": scenario.id, "title": scenario.title, "fault": scenario.fault}
