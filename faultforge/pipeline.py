"""Reproduce → repair → replayed verification, for one repo."""

import json
from dataclasses import dataclass
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
) -> PipelineResult:
    events.emit("pipeline_started", repo=source.name, scenarios=[_describe(s) for s in scenarios])
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
                sandbox, base, source, scenarios, candidates, events, max_workers, baseline
            )
            if result.winner is None:
                revised = _revise(llm, source, result, failure, failures, events)
                if revised:
                    second = replay(
                        sandbox, base, source, scenarios, revised, events, max_workers, baseline
                    )
                    result.report.results.extend(second.results)
            result.status = Status.REPAIRED if result.winner else Status.NO_REPAIR

    events.emit(
        "pipeline_finished",
        status=result.status.value,
        winner=result.winner.candidate.id if result.winner else None,
    )
    return result


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
