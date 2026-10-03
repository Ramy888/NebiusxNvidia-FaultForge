import argparse
import os
import sys
from pathlib import Path

from .auto import auto_scenarios
from .demo import EXAMPLES
from .events import EventLog
from .llm import LLMError
from .pipeline import Status, load_stub, run_pipeline
from .pr import PullRequestError, open_pull_request, plan_pull_request
from .report import render_markdown
from .research import TavilyResearcher
from .sandbox import LocalSandbox, SandboxError
from .scenarios import scenario_from_file

# Remote sandboxes start from a bare Python image; local runs reuse FaultForge's interpreter.
REMOTE_SETUP = "python -m pip install -q httpx pytest"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="faultforge")
    commands = parser.add_subparsers(dest="command", required=True)

    demo = commands.add_parser("demo", help="offline demo on the bundled order service")
    demo.add_argument("--example", choices=sorted(EXAMPLES), default="order-service")
    demo.add_argument("--out", type=Path, help="write the markdown report here")
    demo.add_argument(
        "--pr-preview", action="store_true", help="show the pull request it would open"
    )

    run = commands.add_parser("run", help="run scenarios against a repo")
    run.add_argument("repo", type=Path)
    run.add_argument(
        "--scenario",
        type=Path,
        action="append",
        help="scenario test file (repeatable); omit to discover and generate scenarios",
    )
    run.add_argument("--stub", type=Path, help="recorded model responses instead of Nemotron")
    run.add_argument(
        "--sandbox",
        choices=["local", "contree"],
        default=os.environ.get("FAULTFORGE_SANDBOX", "local"),
    )
    run.add_argument("--setup", help="one-time command run before the baseline")
    run.add_argument("--candidates", type=int, default=3)
    run.add_argument("--out", type=Path)
    run.add_argument(
        "--pr-preview", action="store_true", help="show the pull request it would open"
    )
    run.add_argument(
        "--open-pr",
        action="store_true",
        help="commit the repair on a new branch in REPO, push it and open a GitHub pull request",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            assets, repo = EXAMPLES[args.example]
            scenario_files = sorted((assets / "scenarios").glob("*.py"))
            llm, sandbox_name, setup = load_stub(assets / "llm_responses.json"), "local", None
        else:
            repo, scenario_files = args.repo, args.scenario
            llm = load_stub(args.stub) if args.stub else _live_llm()
            sandbox_name = args.sandbox
            setup = args.setup or (REMOTE_SETUP if sandbox_name == "contree" else None)
    except LLMError as error:
        print(f"faultforge: {error}", file=sys.stderr)
        return 2

    events = EventLog()
    events.subscribe(_print_progress)
    found = None
    if scenario_files:
        scenarios = [scenario_from_file(p) for p in scenario_files]
    else:
        found = auto_scenarios(llm, repo, _researcher(), events)
        scenarios = found.scenarios
        if not scenarios:
            print("faultforge: no testable HTTP dependency scenarios found", file=sys.stderr)
            return 1
    try:
        sandbox = _sandbox(sandbox_name)
    except SandboxError as error:
        print(f"faultforge: {error}", file=sys.stderr)
        return 2
    with sandbox:
        result = run_pipeline(
            repo,
            scenarios,
            llm,
            sandbox,
            events,
            max_candidates=getattr(args, "candidates", 3),
            setup=setup,
        )

    markdown = render_markdown(result, found)
    if args.out:
        args.out.write_text(markdown)
    else:
        print(markdown)
    if result.winner and (args.pr_preview or getattr(args, "open_pr", False)):
        plan = plan_pull_request(result, found)
        live = getattr(args, "open_pr", False)
        try:
            outcome = open_pull_request(plan, repo, dry_run=not live)
        except PullRequestError as error:
            print(f"faultforge: {error}", file=sys.stderr)
            return 1
        print(
            f"• pull request {'opened' if live else 'preview'}: {outcome['branch']}",
            file=sys.stderr,
        )
        print(f"  {outcome.get('url') or plan.title}", file=sys.stderr)
        for path in outcome["files"]:
            print(f"  {path}", file=sys.stderr)
    if usage := getattr(llm, "usage", None):
        print(f"• token usage: {usage}", file=sys.stderr)
    return 0 if result.status in (Status.REPAIRED, Status.NO_FAILURE) else 1


def _live_llm():
    from .llm.token_factory import TokenFactoryConfig, TokenFactoryLLM

    return TokenFactoryLLM(TokenFactoryConfig.from_env(os.environ))


def _researcher():
    key = os.environ.get("TAVILY_API_KEY")
    return TavilyResearcher(key) if key else None


def _sandbox(name: str):
    if name == "contree":
        from .sandbox.contree import ContreeSandbox

        return ContreeSandbox()
    return LocalSandbox()


def _print_progress(event) -> None:
    if event.type == "run_finished":
        data = event.data
        print(f"  [{data['branch']}] {data['check']}: {data['outcome']}", file=sys.stderr)
    elif event.type in ("failure_reproduced", "repairs_planned", "pipeline_finished"):
        print(f"• {event.type.replace('_', ' ')}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
