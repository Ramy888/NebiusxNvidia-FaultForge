"""Nebius Token Factory Sandboxes (Contree) behind the Sandbox contract.

Each run of an image yields a new image, kept (`disposable=False`) so later runs can branch
from it. Repo files and patches are uploaded as bytes with the run itself.
Requires the optional extra: `uv sync --extra contree`.
"""

import time
import uuid
from pathlib import Path

from .base import RunResult, SandboxError, Snapshot, safe_relative_path

SKIP_DIRS = {".venv", ".git", "__pycache__", "node_modules", ".pytest_cache"}
TIMEOUT_ERRORS = ("OperationTimedOutError", "ApiTimeoutError", "FakeTimeoutError")


class ContreeSandbox:
    def __init__(
        self,
        client=None,
        base_image: str = "python:3.12-slim",
        workdir: str = "/workspace",
    ):
        self._client = client or _default_client()
        self._base_image = base_image
        self._workdir = workdir.rstrip("/")

    def __enter__(self) -> "ContreeSandbox":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        """Result images expire on the service side; nothing to clean up locally."""

    def create(self, source: Path) -> Snapshot:
        files = {
            self._remote(path.relative_to(source).as_posix()): path.read_bytes()
            for path in sorted(source.rglob("*"))
            if path.is_file() and not SKIP_DIRS.intersection(path.relative_to(source).parts)
        }
        try:
            image = self._settle(self._client.images.use(self._base_image).apply_files(files=files))
        except Exception as error:
            raise SandboxError(f"could not upload {source.name} to Contree: {error}") from error
        return Snapshot(id=str(image.uuid))

    def run(
        self,
        snapshot: Snapshot,
        command: str,
        files: dict[str, str] | None = None,
        timeout: float = 120,
    ) -> RunResult:
        uploads = {
            self._remote(safe_relative_path(path).as_posix()): content.encode()
            for path, content in (files or {}).items()
        }
        image = self._image(snapshot)
        started = time.monotonic()
        try:
            result = image.run(
                shell=command,
                cwd=self._workdir,
                files=uploads,
                timeout=timeout,
                disposable=False,
            ).wait()
        except Exception as error:
            if type(error).__name__ in TIMEOUT_ERRORS:
                return RunResult(snapshot, -9, "", str(error), True, time.monotonic() - started)
            raise SandboxError(f"Contree run failed: {error}") from error
        return RunResult(
            snapshot=Snapshot(id=str(result.uuid)),
            exit_code=result.exit_code,
            stdout=_text(result.stdout),
            stderr=_text(result.stderr),
            timed_out=False,
            duration_s=time.monotonic() - started,
        )

    def _image(self, snapshot: Snapshot):
        try:
            return self._client.images.use(uuid.UUID(snapshot.id))
        except Exception as error:
            raise SandboxError(f"unknown snapshot {snapshot.id}") from error

    def _remote(self, relative: str) -> str:
        return f"{self._workdir}/{relative}"

    @staticmethod
    def _settle(image):
        """Block until an image operation has finished, unless it already has.

        Verified live: `apply_files()` returns an image that is already SUCCEEDED, and calling
        `wait()` on it raises; only PREPARING/PREPARED images can be waited on.
        """
        state = str(getattr(image, "state", "")).upper()
        if state and "PREPAR" not in state:
            return image
        wait = getattr(image, "wait", None)
        return wait() if callable(wait) else image


def _text(value) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else str(value)


def _default_client():
    try:
        from contree_sdk import ContreeSync
    except ImportError as error:
        raise SandboxError("Contree SDK missing: run `uv sync --extra contree`") from error
    # Credentials come from `contree auth` (~/.config/contree/auth.ini) or CONTREE_* env vars.
    return ContreeSync()
