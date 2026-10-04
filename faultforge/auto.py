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
    """Keep generated tests that are sound; a broken one gets one fix attempt."""
    kept, retry = [], []
    for scenario, problem in _problems(sandbox, source, scenarios, events, setup):
        if problem is None:
            kept.append(scenario)
            continue
        fixed = writer.fix(scenario, problem)
        if fixed is None:
            events.emit("scenario_discarded", scenario=scenario.id, reason=problem[:400])
        else:
            retry.append(fixed)
    for scenario, problem in _problems(sandbox, source, retry, events, setup):
        if problem is None:
            kept.append(scenario)
        else:
            events.emit("scenario_discarded", scenario=scenario.id, reason=problem[:400])
    return kept


def _problems(sandbox, source, scenarios, events, setup) -> list[tuple[Scenario, str | None]]:
    if not scenarios:
        return []
    base = prepare_workspace(sandbox, source, scenarios, setup)
    baseline = run_baseline(sandbox, base, scenarios, events)
    results = []
    for scenario in scenarios:
        check = baseline.scenarios[scenario.id]
        broken = scenario_is_broken(check, scenario.test_path)
        results.append((scenario, (check.output or check.message) if broken else None))
    return results
