from pathlib import Path

import pytest

from faultforge.sandbox import SandboxError
from faultforge.sandbox.contree import ContreeSandbox

from .fake_contree import FakeContree


@pytest.fixture
def source(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "hello.txt").write_text("hello\n")
    (repo / "pkg" / "mod.py").write_text("X = 1\n")
    (repo / ".venv").mkdir()
    (repo / ".venv" / "huge.bin").write_text("skip me")
    return repo


@pytest.fixture
def client() -> FakeContree:
    return FakeContree()


@pytest.fixture
def sandbox(client) -> ContreeSandbox:
    return ContreeSandbox(client=client)


def test_create_uploads_the_repo_under_the_workdir(sandbox, client, source):
    snapshot = sandbox.create(source)

    files = client.images.use(snapshot.id).files
    assert files["/workspace/hello.txt"] == b"hello\n"
    assert files["/workspace/pkg/mod.py"] == b"X = 1\n"
    assert not any(".venv" in path for path in files)


def test_run_returns_output_and_exit_code(sandbox, source):
    base = sandbox.create(source)

    result = sandbox.run(base, "cat hello.txt && exit 3")

    assert result.stdout == "hello\n"
    assert result.exit_code == 3


def test_files_are_uploaded_as_bytes_into_the_workdir(sandbox, client, source):
    base = sandbox.create(source)

    result = sandbox.run(base, "cat pkg/new.txt", files={"pkg/new.txt": "patched\n"})

    assert result.stdout == "patched\n"
    run_files = client.images.use(result.snapshot.id).run_kwargs["files"]
    assert run_files == {"/workspace/pkg/new.txt": b"patched\n"}


def test_result_images_are_kept_for_branching(sandbox, client, source):
    base = sandbox.create(source)

    result = sandbox.run(base, "true")

    assert client.images.use(result.snapshot.id).run_kwargs["disposable"] is False


def test_runs_from_one_snapshot_are_isolated(sandbox, source):
    base = sandbox.create(source)

    sandbox.run(base, "echo changed > hello.txt")
    sibling = sandbox.run(base, "cat hello.txt")

    assert sibling.stdout == "hello\n"


def test_each_run_produces_a_new_snapshot_holding_its_changes(sandbox, source):
    base = sandbox.create(source)

    first = sandbox.run(base, "echo changed > hello.txt")
    follow_up = sandbox.run(first.snapshot, "cat hello.txt")

    assert first.snapshot != base
    assert follow_up.stdout == "changed\n"


def test_timeout_is_reported_not_raised(sandbox, source):
    base = sandbox.create(source)

    result = sandbox.run(base, "sleep 5", timeout=0.5)

    assert result.timed_out
    assert result.snapshot == base


def test_files_outside_the_repo_are_refused(sandbox, source):
    base = sandbox.create(source)

    with pytest.raises(SandboxError):
        sandbox.run(base, "true", files={"../../etc/passwd": "x"})


def test_unknown_snapshot_is_a_sandbox_error(sandbox, source):
    sandbox.create(source)

    with pytest.raises(SandboxError):
        sandbox.run(type(sandbox.create(source))(id="nope"), "true")


def test_an_upload_that_is_already_finished_is_not_waited_on(client, source):
    """The real SDK returns apply_files() results already SUCCEEDED; wait() then raises."""

    class FinishedImage:
        state = "ImageState.SUCCEEDED"

        def __init__(self, inner):
            self._inner = inner
            self.uuid = inner.uuid

        def wait(self):
            raise RuntimeError("cannot wait on a finished image")

    base = client.images.base
    original = base.apply_files
    base.apply_files = lambda files: FinishedImage(original(files))

    snapshot = ContreeSandbox(client=client).create(source)

    assert snapshot.id
