"""Sandbox contract: every run starts from a snapshot and produces a new one.

This mirrors Token Factory Sandboxes, where each run of an image yields a new image, so
branching is simply several runs from the same snapshot.
"""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol


class SandboxError(Exception):
    pass


@dataclass(frozen=True)
class Snapshot:
    id: str


@dataclass(frozen=True)
class RunResult:
    snapshot: Snapshot
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float


class Sandbox(Protocol):
    def create(self, source: Path) -> Snapshot: ...

    def run(
        self,
        snapshot: Snapshot,
        command: str,
        files: dict[str, str] | None = None,
        timeout: float = 120,
    ) -> RunResult: ...

    def close(self) -> None: ...


def safe_relative_path(path: str) -> PurePosixPath:
    """Reject absolute paths and anything that climbs out of the repo."""
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise SandboxError(f"refusing to write outside the repo: {path!r}")
    return candidate


def ensure_isolated_for_live(sandbox_name: str, env: dict | None = None) -> None:
    """Live mode executes model-written code, so it needs a VM-isolated sandbox by default."""
    import os

    env = os.environ if env is None else env
    if sandbox_name == "local" and env.get("FAULTFORGE_ALLOW_LOCAL_LIVE") != "1":
        raise SandboxError(
            "live mode runs model-written code: use --sandbox contree (an isolated sandbox), or "
            "set FAULTFORGE_ALLOW_LOCAL_LIVE=1 on a machine or container you are willing to risk"
        )
