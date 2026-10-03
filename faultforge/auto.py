"""Automatic mode: find the dependency, research it, and write failure scenarios for it."""

from dataclasses import dataclass, field
from pathlib import Path

from .discovery import Dependency, discover
from .events import EventLog
from .llm import LLM
from .models import Scenario
from .research import Research, TavilyResearcher, research_dependency
from .scenarios import generate_scenarios


@dataclass
class AutoScenarios:
    dependency: Dependency | None = None
    research: Research = field(default_factory=Research)
    scenarios: list[Scenario] = field(default_factory=list)


def auto_scenarios(
    llm: LLM, source: Path, researcher: TavilyResearcher | None, events: EventLog
) -> AutoScenarios:
    dependencies = discover(llm, source, events)
    if not dependencies:
        return AutoScenarios()
    dependency = dependencies[0]
    research = research_dependency(researcher, dependency, events)
    scenarios = generate_scenarios(llm, source, dependency, research.notes, events)
    return AutoScenarios(dependency, research, scenarios)
