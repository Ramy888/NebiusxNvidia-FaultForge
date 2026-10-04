"""Automatic mode: find the dependency, research it, and write failure scenarios for it."""

from dataclasses import dataclass, field
from pathlib import Path

from .discovery import Dependency, discover
from .events import EventLog
from .llm import LLM
from .models import Scenario
from .replay import run_baseline
from .research import Research, TavilyResearcher, research_dependency
from .sandbox import Sandbox
from .scenarios import ScenarioWriter, scenario_is_broken
from .workspace import prepare_workspace


@dataclass
class AutoScenarios:
    dependency: Dependency | None = None
    research: Research = field(default_factory=Research)
    scenarios: list[Scenario] = field(default_factory=list)


def auto_scenarios(
    llm: LLM,
    source: Path,
    researcher: TavilyResearcher | None,
    events: EventLog,
    sandbox: Sandbox | None = None,
    setup: str | None = None,
) -> AutoScenarios:
    dependencies = discover(llm, source, events)
    if not dependencies:
        return AutoScenarios()
    dependency = dependencies[0]
    research = research_dependency(researcher, dependency, events)
    writer = ScenarioWriter(llm, source, dependency, research.notes, events)
    scenarios = writer.write_all()
    if sandbox is not None:
        scenarios = validate_scenarios(writer, sandbox, source, scenarios, events, setup)
    return AutoScenarios(dependency, research, scenarios)


def validate_scenarios(
    writer: ScenarioWriter,
    sandbox: Sandbox,
    source: Path,
    scenarios: list[Scenario],
    events: EventLog,
    setup: str | None = None,
) -> list[Scenario]:
    """Run each generated test once; a test broken by its own mistake gets one fix attempt."""
    if not scenarios:
        return []
    baseline = run_baseline(
        sandbox, prepare_workspace(sandbox, source, scenarios, setup), scenarios, events
    )
    kept, retry = [], []
    for scenario in scenarios:
        check = baseline.scenarios[scenario.id]
        if not scenario_is_broken(check):
            kept.append(scenario)
            continue
        fixed = writer.fix(scenario, check.output or check.message)
        if fixed is None:
            events.emit("scenario_discarded", scenario=scenario.id, reason=check.message)
        else:
            retry.append(fixed)
    if retry:
        rechecked = run_baseline(
            sandbox, prepare_workspace(sandbox, source, retry, setup), retry, events
        )
        for scenario in retry:
            check = rechecked.scenarios[scenario.id]
            if scenario_is_broken(check):
                events.emit("scenario_discarded", scenario=scenario.id, reason=check.message)
            else:
                kept.append(scenario)
    return kept
