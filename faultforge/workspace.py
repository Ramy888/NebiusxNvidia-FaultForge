from pathlib import Path

from .models import Scenario
from .sandbox import Sandbox, SandboxError, Snapshot

FAULTKIT_DIR = Path(__file__).parent / "faultkit"


def faultkit_files() -> dict[str, str]:
    return {f"faultkit/{path.name}": path.read_text() for path in FAULTKIT_DIR.glob("*.py")}


def prepare_workspace(sandbox: Sandbox, source: Path, scenarios: list[Scenario]) -> Snapshot:
    """Snapshot of the repo with the fault kit and every scenario test installed."""
    files = faultkit_files() | {scenario.test_path: scenario.test_code for scenario in scenarios}
    result = sandbox.run(sandbox.create(source), "true", files=files, timeout=60)
    if result.exit_code != 0:
        raise SandboxError(f"could not prepare workspace: {result.stderr.strip()}")
    return result.snapshot
