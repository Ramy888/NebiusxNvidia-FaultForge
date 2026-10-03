import shutil
import subprocess
import sys
from pathlib import Path

from faultforge.demo import ORDER_SERVICE

ROOT = Path(__file__).resolve().parents[1]


def run_scenario_against_example(tmp_path: Path) -> subprocess.CompletedProcess:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "examples" / "order-service", repo)
    shutil.copytree(ROOT / "faultforge" / "faultkit", repo / "faultkit")
    shutil.copy(
        ORDER_SERVICE / "scenarios" / "timeout_duplicate.py",
        repo / "tests" / "test_ff_timeout_duplicate.py",
    )
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_ff_timeout_duplicate.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_timeout_scenario_reproduces_duplicate_fulfillment(tmp_path):
    result = run_scenario_against_example(tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "one order created 2 fulfillments at the provider" in result.stdout
