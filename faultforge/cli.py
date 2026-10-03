import argparse
import sys
from pathlib import Path

from .demo import ORDER_SERVICE, ORDER_SERVICE_REPO
from .events import EventLog
from .pipeline import Status, load_stub, run_pipeline
from .report import render_markdown
from .sandbox import LocalSandbox
from .scenarios import scenario_from_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="faultforge")
    commands = parser.add_subparsers(dest="command", required=True)

    demo = commands.add_parser("demo", help="offline demo on the bundled order service")
    demo.add_argument("--out", type=Path, help="write the markdown report here")

    run = commands.add_parser("run", help="run scenarios against a repo")
    run.add_argument("repo", type=Path)
    run.add_argument("--scenario", type=Path, action="append", required=True)
    run.add_argument("--stub", type=Path, help="recorded model responses (offline)")
    run.add_argument("--out", type=Path)

    args = parser.parse_args(argv)
    if args.command == "demo":
        repo, scenario_files = (
            ORDER_SERVICE_REPO,
            sorted((ORDER_SERVICE / "scenarios").glob("*.py")),
        )
        llm = load_stub(ORDER_SERVICE / "llm_responses.json")
    else:
        repo, scenario_files = args.repo, args.scenario
        if not args.stub:
            parser.error("live models arrive with the Token Factory client; pass --stub for now")
        llm = load_stub(args.stub)

    events = EventLog()
    events.subscribe(_print_progress)
    with LocalSandbox() as sandbox:
        result = run_pipeline(
            repo, [scenario_from_file(p) for p in scenario_files], llm, sandbox, events
        )

    markdown = render_markdown(result)
    if args.out:
        args.out.write_text(markdown)
    else:
        print(markdown)
    return 0 if result.status in (Status.REPAIRED, Status.NO_FAILURE) else 1


def _print_progress(event) -> None:
    if event.type == "run_finished":
        data = event.data
        print(f"  [{data['branch']}] {data['check']}: {data['outcome']}", file=sys.stderr)
    elif event.type in ("failure_reproduced", "repairs_planned", "pipeline_finished"):
        print(f"• {event.type.replace('_', ' ')}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
