"""Automatic mode: find the dependency, research it, and write failure scenarios for it."""

from dataclasses import dataclass, field
from pathlib import Path

from .discovery import Dependency, discover
from .events import EventLog
from .llm import LLM
from .models import Scenario
from .replay import PYTEST, Outcome, classify, run_baseline
from .research import Research, TavilyResearcher, research_dependency
from .sandbox import Sandbox
from .scenarios import ScenarioWriter, scenario_is_broken
from .workspace import prepare_workspace

CONTROL_TIMEOUT_S = 120


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
    """Keep generated tests that are sound; a broken one gets one fix attempt.

    Sound means: with the fault injected the test runs (pass or fail on its assertion), and with
    the fault switched off it passes. A test that fails even against a healthy dependency is
    testing its own mistake, not the application.
    """
    kept, retry = [], []
    for scenario, problem in _problems(sandbox, source, scenarios, events, setup):
        if problem is None:
            kept.append(scenario)
            continue
        fixed = writer.fix(scenario, problem)
        if fixed is None:
            events.emit("scenario_discarded", scenario=scenario.id, reason=problem[-300:])
        else:
            retry.append(fixed)
    for scenario, problem in _problems(sandbox, source, retry, events, setup):
        if problem is None:
            kept.append(scenario)
        else:
            events.emit("scenario_discarded", scenario=scenario.id, reason=problem[-300:])
    return kept


def _problems(sandbox, source, scenarios, events, setup) -> list[tuple[Scenario, str | None]]:
    if not scenarios:
        return []
    base = prepare_workspace(sandbox, source, scenarios, setup)
    baseline = run_baseline(sandbox, base, scenarios, events)
    results = []
    for scenario in scenarios:
        check = baseline.scenarios[scenario.id]
        if scenario_is_broken(check):
            results.append((scenario, check.output or check.message))
            continue
        control = sandbox.run(
            base, f"FAULTKIT_DISABLED=1 {PYTEST} {scenario.test_path}", timeout=CONTROL_TIMEOUT_S
        )
        outcome, message = classify(control)
        if outcome is Outcome.PASSED:
            results.append((scenario, None))
        else:
            output = (control.stdout + control.stderr)[-2500:]
            results.append(
                (scenario, f"The test fails even without the fault injected: {message}\n{output}")
            )
    return results
