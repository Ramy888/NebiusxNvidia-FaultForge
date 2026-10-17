"""Automatic mode: find the dependency, research it, and write failure scenarios for it."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .discovery import Dependency, discover
from .events import EventLog
from .llm import LLM, LLMError, parse_json
from .models import Scenario
from .replay import Outcome, run_baseline
from .research import Research, TavilyResearcher, research_dependency
from .sandbox import Sandbox
from .scenarios import ScenarioWriter, scenario_is_broken
from .workspace import prepare_workspace


@dataclass
class AutoScenarios:
    dependency: Dependency | None = None
    research: Research = field(default_factory=Research)
    scenarios: list[Scenario] = field(default_factory=list)
    # rewrites a test the repairs showed to be mistaken (see pipeline.suspect_scenarios)
    retriage: Callable[[Scenario, str], Scenario | None] | None = None


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
    retriage = None
    if sandbox is not None:
        scenarios = validate_scenarios(writer, sandbox, source, scenarios, events, setup)

        def retriage(scenario: Scenario, evidence: str) -> Scenario | None:
            fixed = writer.fix(scenario, evidence)
            if fixed is None:
                return None
            # check it runs and triage it again, without a second fix: one rewrite only
            [(checked, problem)] = _problems(writer, sandbox, source, [fixed], events, setup)
            if problem is not None:
                events.emit("scenario_discarded", scenario=fixed.id, reason=problem[:400])
                return None
            return checked

    return AutoScenarios(dependency, research, scenarios, retriage)


def validate_scenarios(
    writer: ScenarioWriter,
    sandbox: Sandbox,
    source: Path,
    scenarios: list[Scenario],
    events: EventLog,
    setup: str | None = None,
) -> list[Scenario]:
    """Keep generated tests that are sound; a broken one gets one fix attempt."""
    kept, retry, triaged = [], [], set()
    for scenario, problem in _problems(writer, sandbox, source, scenarios, events, setup):
        if problem is None:
            kept.append(scenario)
            continue
        if problem.startswith(TRIAGE_FINDING):
            triaged.add(scenario.id)
        fixed = writer.fix(scenario, problem)
        if fixed is None:
            events.emit("scenario_discarded", scenario=scenario.id, reason=problem[:400])
        else:
            retry.append(fixed)
    for scenario, problem in _problems(
        writer, sandbox, source, retry, events, setup, must_fail=triaged
    ):
        if problem is None:
            kept.append(scenario)
        else:
            events.emit("scenario_discarded", scenario=scenario.id, reason=problem[:400])
    return kept


def _problems(
    writer, sandbox, source, scenarios, events, setup, must_fail: set[str] = frozenset()
) -> list[tuple[Scenario, str | None]]:
    """`must_fail`: rewrites of tests triage flagged. The original failed on this code, so a
    rewrite that now passes has usually been bent to assert the bug instead of the invariant."""
    if not scenarios:
        return []
    base = prepare_workspace(sandbox, source, scenarios, setup)
    baseline = run_baseline(sandbox, base, scenarios, events, label="validation")
    results = []
    for scenario in scenarios:
        check = baseline.scenarios[scenario.id]
        if scenario_is_broken(check, scenario.test_path):
            results.append((scenario, check.output or check.message))
        elif check.outcome is Outcome.FAILED:
            results.append((scenario, triage(writer, scenario, check, events)))
        elif scenario.id in must_fail:
            results.append((scenario, REWRITE_PASSES))
        else:
            results.append((scenario, None))
    return results


TRIAGE_FINDING = "Review found a mistake in the test, not the application"
REWRITE_PASSES = (
    "The rewritten test no longer fails on the original code, so it no longer checks the "
    "invariant the first version caught; dropped rather than kept as a gate."
)

TRIAGE_SYSTEM = """A failure-injection test failed against a Python application. Decide whether
the failure shows a genuine bug in how the application handles the dependency failure, or a
mechanical mistake in the test itself: for example the test reads data it never created, uses the
fake dependency or fault kit differently than documented, or asserts on the wrong object.
The test asserts what SHOULD happen under the fault, not what the code does today. If the
application's own reaction to the fault (retrying, trusting the response, skipping a check) is
what breaks the assertion, that is an application_bug, even when the current code makes the
failure inevitable: a retry that creates a second order or charge is the bug being caught.
Answer test_mistake only when you can name the mechanical error. Respond with JSON only:
{"verdict": "application_bug" or "test_mistake", "reason": "one sentence"}"""


def triage(writer, scenario: Scenario, check, events: EventLog) -> str | None:
    """Ask the reasoning model whether a reproduced failure is the app's fault or the test's.

    Returns a problem description for a test mistake, or None for a genuine application bug.
    Unclear answers count as application bugs: the repair phase will judge them anyway.
    """
    prompt = (
        f"{writer.context}\n\n## Failing test {scenario.test_path}\n```python\n"
        f"{scenario.test_code}```\n\n## pytest output\n```\n{check.output[-3000:]}\n```"
    )
    try:
        answer = parse_json(writer.llm.complete("plan", TRIAGE_SYSTEM, prompt))
    except LLMError as error:
        events.emit("scenario_triaged", scenario=scenario.id, verdict="unknown", reason=str(error))
        return None
    verdict = str(answer.get("verdict", "application_bug"))
    reason = str(answer.get("reason", ""))
    events.emit("scenario_triaged", scenario=scenario.id, verdict=verdict, reason=reason)
    if verdict != "test_mistake":
        return None
    return f"{TRIAGE_FINDING}: {reason}\n{check.output}"
