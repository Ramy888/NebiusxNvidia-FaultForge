"""In-memory stand-in for the slice of contree_sdk.ContreeSync that ContreeSandbox uses.

Images are immutable dicts of absolute path -> bytes; `run` really executes the shell command in
a scratch directory so the adapter's contract can be tested without the service.
"""

import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


class FakeTimeoutError(Exception):
    pass


class FakeImage:
    def __init__(self, registry: dict, files: dict[str, bytes]):
        self._registry = registry
        self.files = files
        self.uuid = uuid.uuid4()
        registry[str(self.uuid)] = self
        self.stdout = self.stderr = ""
        self.exit_code = None
        self._pending = None
        self.run_kwargs = None

    def apply_files(self, files: dict[str, bytes]) -> "FakeImage":
        return FakeImage(self._registry, self.files | files)

    def run(self, *, shell, cwd, files, timeout, disposable, **_):
        image = FakeImage(self._registry, self.files | (files or {}))
        image._pending = (shell, cwd, timeout)
        image.run_kwargs = {"disposable": disposable, "cwd": cwd, "files": files}
        return image

    def wait(self) -> "FakeImage":
        if self._pending is None:
            return self
        shell, cwd, timeout = self._pending
        scratch = Path(tempfile.mkdtemp())
        try:
            for path, content in self.files.items():
                target = scratch / path.lstrip("/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            workdir = scratch / cwd.lstrip("/")
            env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin"}
            try:
                done = subprocess.run(
                    ["bash", "-c", shell],
                    cwd=workdir,
                    env=env,
                    capture_output=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as error:
                raise FakeTimeoutError("operation timed out") from error
            self.stdout, self.stderr, self.exit_code = done.stdout, done.stderr, done.returncode
            self.files = {
                "/" + p.relative_to(scratch).as_posix(): p.read_bytes()
                for p in scratch.rglob("*")
                if p.is_file()
            }
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        return self


class FakeImages:
    def __init__(self):
        self.registry: dict[str, FakeImage] = {}
        FakeImage(self.registry, {})  # placeholder so registry is non-empty
        self.base = FakeImage(self.registry, {})

    def use(self, ref):
        ref = str(ref)
        if ref in self.registry:
            return self.registry[ref]
        if ref == "python:3.12-slim":
            return self.base
        raise KeyError(ref)


class FakeContree:
    def __init__(self):
        self.images = FakeImages()
