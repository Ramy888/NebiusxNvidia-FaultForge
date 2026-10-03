import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from .base import RunResult, SandboxError, Snapshot, safe_relative_path


class LocalSandbox:
    """Snapshots are directory copies; commands run as local subprocesses.

    Not an isolation boundary: use it only for trusted, offline development.
    """

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="faultforge-"))
        # Allowlist, never os.environ: sandboxed code is model-written and must not see API keys.
        self._env = {
            "PATH": f"{Path(sys.executable).parent}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "HOME": str(self.root),
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    def __enter__(self) -> "LocalSandbox":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def create(self, source: Path) -> Snapshot:
        snapshot = Snapshot(id=uuid.uuid4().hex)
        shutil.copytree(source, self._path(snapshot), ignore=shutil.ignore_patterns(".venv"))
        return snapshot

    def run(
        self,
        snapshot: Snapshot,
        command: str,
        files: dict[str, str] | None = None,
        timeout: float = 120,
    ) -> RunResult:
        source = self._path(snapshot)
        if not source.is_dir():
            raise SandboxError(f"unknown snapshot {snapshot.id}")
        result_snapshot = Snapshot(id=uuid.uuid4().hex)
        workdir = self._path(result_snapshot)
        shutil.copytree(source, workdir)
        try:
            for path, content in (files or {}).items():
                target = workdir / safe_relative_path(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            return self._execute(command, workdir, result_snapshot, timeout)
        except BaseException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise

    def _execute(self, command: str, workdir: Path, snapshot: Snapshot, timeout: float):
        started = time.monotonic()
        process = subprocess.Popen(
            ["bash", "-c", command],
            cwd=workdir,
            env=self._env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            timed_out = True
        return RunResult(
            snapshot=snapshot,
            exit_code=process.returncode if not timed_out else -signal.SIGKILL,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            duration_s=time.monotonic() - started,
        )

    def _path(self, snapshot: Snapshot) -> Path:
        return self.root / snapshot.id
