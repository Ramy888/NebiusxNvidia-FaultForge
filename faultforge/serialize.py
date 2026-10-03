"""JSON shapes for the API and UI."""

from .pipeline import PipelineResult
from .replay import Check
from .report import render_markdown


def check_to_dict(check: Check) -> dict:
    return {
        "outcome": check.outcome.value,
        "message": check.message,
        "duration_s": round(check.duration_s, 3),
        "output": check.output,
    }


def result_to_dict(result: PipelineResult, found=None) -> dict:
    data = {
        "repo": result.repo,
        "status": result.status.value,
        "target": result.target.id if result.target else None,
        "winner": result.winner.candidate.id if result.winner else None,
        "existing_tests": check_to_dict(result.baseline.existing_tests),
        "scenarios": [
            {
                "id": s.id,
                "title": s.title,
                "fault": s.fault,
                "test_path": s.test_path,
                "test_code": s.test_code,
                "baseline": check_to_dict(result.baseline.scenarios[s.id]),
            }
            for s in result.scenarios
        ],
        "candidates": [
            {
                "id": r.candidate.id,
                "summary": r.candidate.summary,
                "accepted": r.accepted,
                "rejection_reason": r.rejection_reason,
                "diff": r.diff,
                "diff_lines": r.diff_lines,
                "fixed": r.fixed,
                "regressed": r.regressed,
                "existing_tests": check_to_dict(r.existing_tests),
                "scenarios": {k: check_to_dict(c) for k, c in r.scenarios.items()},
            }
            for r in (result.report.ranking if result.report else [])
        ],
        "dependency": None,
        "research": [],
        "markdown": render_markdown(result, found),
    }
    if found is not None and found.dependency is not None:
        data["dependency"] = {
            "name": found.dependency.name,
            "operation": found.dependency.operation,
            "call_sites": [s.ref for s in found.dependency.call_sites],
        }
        data["research"] = [{"title": s.title, "url": s.url} for s in found.research.sources]
    return data
