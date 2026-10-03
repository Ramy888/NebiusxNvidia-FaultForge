"""Reproduce → repair → replayed verification, for one repo."""

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .events import EventLog
from .llm import LLM, StubLLM
from .models import Scenario
from .repair import generate_repairs
from .replay import Branch, CandidateResult, Outcome, ReplayReport, replay, run_baseline
from .sandbox import Sandbox
from .workspace import prepare_workspace


class Status(Enum):
    REPAIRED = "repaired"
    NO_REPAIR = "no_repair"
    NO_FAILURE = "no_failure"
    BROKEN_BASELINE = "broken_baseline"


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
) -> PipelineResult:
    events.emit("pipeline_started", repo=source.name, scenarios=[_describe(s) for s in scenarios])
    base = prepare_workspace(sandbox, source, scenarios)
    events.emit("workspace_ready", snapshot=base.id)
    baseline = run_baseline(sandbox, base, scenarios, events, max_workers)
    result = PipelineResult(source.name, Status.NO_FAILURE, scenarios, baseline)

    if baseline.existing_tests.outcome is not Outcome.PASSED:
        result.status = Status.BROKEN_BASELINE
    else:
        failing = [s for s in scenarios if baseline.scenarios[s.id].outcome is Outcome.FAILED]
        if failing:
            result.target = failing[0]
            failure = baseline.scenarios[result.target.id].message
            events.emit("failure_reproduced", scenario=result.target.id, message=failure)
            candidates = generate_repairs(
                llm, source, result.target, failure, events, max_candidates
            )
            result.report = replay(
                sandbox, base, source, scenarios, candidates, events, max_workers, baseline
            )
            result.status = Status.REPAIRED if result.winner else Status.NO_REPAIR

    events.emit(
        "pipeline_finished",
        status=result.status.value,
        winner=result.winner.candidate.id if result.winner else None,
    )
    return result


def _describe(scenario: Scenario) -> dict:
    return {"id": scenario.id, "title": scenario.title, "fault": scenario.fault}
