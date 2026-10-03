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
