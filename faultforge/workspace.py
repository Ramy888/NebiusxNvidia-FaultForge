from pathlib import Path

from .models import Scenario
from .sandbox import Sandbox, SandboxError, Snapshot

FAULTKIT_DIR = Path(__file__).parent / "faultkit"


def faultkit_files() -> dict[str, str]:
    return {f"faultkit/{path.name}": path.read_text() for path in FAULTKIT_DIR.glob("*.py")}


def prepare_workspace(
    sandbox: Sandbox,
    source: Path,
    scenarios: list[Scenario],
    setup: str | None = None,
    setup_timeout: float = 600,
) -> Snapshot:
    """Snapshot of the repo with the fault kit and every scenario test installed.

    `setup` (e.g. installing dependencies) runs once here, so every branch forks from the
    bootstrapped snapshot instead of repeating it.
    """
    files = faultkit_files() | {scenario.test_path: scenario.test_code for scenario in scenarios}
    result = sandbox.run(
        sandbox.create(source), setup or "true", files=files, timeout=setup_timeout
    )
    if result.exit_code != 0:
        raise SandboxError(f"workspace setup failed: {(result.stderr or result.stdout).strip()}")
    return result.snapshot
