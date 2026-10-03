"""Markdown evidence report — also used as the pull request body."""

from .pipeline import PipelineResult, Status

HEADLINES = {
    Status.REPAIRED: "A repair fixed the reproduced failure without breaking existing tests.",
    Status.NO_REPAIR: "The failure was reproduced, but no candidate repair passed verification.",
    Status.NO_FAILURE: "No scenario reproduced a failure.",
    Status.BROKEN_BASELINE: "The existing test suite fails before any fault is injected.",
}


def render_markdown(result: PipelineResult, found=None) -> str:
    lines = [f"# FaultForge report: {result.repo}", "", f"**{HEADLINES[result.status]}**", ""]
    if found is not None and found.dependency is not None:
        dependency = found.dependency
        sites = ", ".join(f"`{s.ref}`" for s in dependency.call_sites)
        lines += [
            "## Dependency",
            "",
            f"**{dependency.name}** — called from {sites}; "
            f"operation at risk: `{dependency.operation}`.",
            "",
        ]
        if found.research.sources:
            lines += ["Research (Tavily) on how the real service fails:", ""]
            lines += [f"- [{s.title}]({s.url})" for s in found.research.sources]
            lines.append("")
    lines += ["## Injected failures", "", "| Scenario | Fault | Baseline | What happened |"]
    lines += ["|---|---|---|---|"]
    for scenario in result.scenarios:
        check = result.baseline.scenarios[scenario.id]
        lines.append(
            f"| {scenario.title} | `{scenario.fault}` | {check.outcome.value} | {check.message} |"
        )
    lines.append(
        f"\nExisting tests at baseline: **{result.baseline.existing_tests.outcome.value}**"
    )

    if result.report:
        lines += ["", "## Candidate repairs", ""]
        header = "| Rank | Candidate | Existing tests | " + " | ".join(
            s.id for s in result.scenarios
        )
        lines += [header + " | Lines changed | Verdict |"]
        lines += ["|" + "---|" * (len(result.scenarios) + 5)]
        for rank, candidate in enumerate(result.report.ranking, start=1):
            transitions = " | ".join(
                f"{result.baseline.scenarios[s.id].outcome.value} → "
                f"{candidate.scenarios[s.id].outcome.value}"
                for s in result.scenarios
            )
            verdict = (
                "accepted" if candidate.accepted else f"rejected: {candidate.rejection_reason}"
            )
            lines.append(
                f"| {rank} | `{candidate.candidate.id}` — {candidate.candidate.summary} "
                f"| {candidate.existing_tests.outcome.value} | {transitions} "
                f"| {candidate.diff_lines} | {verdict} |"
            )

    if result.winner:
        lines += ["", f"## Proposed patch: `{result.winner.candidate.id}`", "", "```diff"]
        lines += [result.winner.diff.rstrip(), "```", ""]
        lines += [f"## Regression test: `{result.target.test_path}`", "", "```python"]
        lines += [result.target.test_code.rstrip(), "```"]
    return "\n".join(lines) + "\n"
