from pathlib import Path

import pytest

from faultforge.sandbox import LocalSandbox, SandboxError


@pytest.fixture
def source(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n")
    return repo


def test_run_returns_output_and_exit_code(source):
    with LocalSandbox() as sandbox:
        base = sandbox.create(source)

        result = sandbox.run(base, "cat hello.txt && exit 3")

    assert result.stdout == "hello\n"
    assert result.exit_code == 3
    assert not result.timed_out


def test_files_are_written_before_the_command_runs(source):
    with LocalSandbox() as sandbox:
        base = sandbox.create(source)

        result = sandbox.run(base, "cat pkg/new.txt", files={"pkg/new.txt": "patched\n"})

    assert result.stdout == "patched\n"


def test_runs_from_one_snapshot_are_isolated(source):
    with LocalSandbox() as sandbox:
        base = sandbox.create(source)

        sandbox.run(base, "echo changed > hello.txt")
        sibling = sandbox.run(base, "cat hello.txt")

    assert sibling.stdout == "hello\n"


def test_each_run_produces_a_new_snapshot_holding_its_changes(source):
    with LocalSandbox() as sandbox:
        base = sandbox.create(source)

        first = sandbox.run(base, "echo changed > hello.txt")
        follow_up = sandbox.run(first.snapshot, "cat hello.txt")

    assert first.snapshot != base
    assert follow_up.stdout == "changed\n"


def test_run_past_its_timeout_is_killed_and_reported(source):
    with LocalSandbox() as sandbox:
        base = sandbox.create(source)

        result = sandbox.run(base, "sleep 30", timeout=0.5)

    assert result.timed_out
    assert result.exit_code != 0
    assert result.duration_s < 5


def test_files_outside_the_repo_are_refused(source):
    with LocalSandbox() as sandbox:
        base = sandbox.create(source)

        with pytest.raises(SandboxError):
            sandbox.run(base, "true", files={"../escape.txt": "x"})


def test_python_on_path_is_the_faultforge_interpreter(source):
    with LocalSandbox() as sandbox:
        base = sandbox.create(source)

        result = sandbox.run(base, "python -c 'import httpx; print(1)'")

    assert result.stdout.strip() == "1"


def test_temporary_directories_are_removed_on_close(source):
    sandbox = LocalSandbox()
    sandbox.create(source)
    root = sandbox.root

    sandbox.close()

    assert not root.exists()


def test_temporary_directories_are_removed_when_the_block_raises(source):
    with pytest.raises(RuntimeError):
        with LocalSandbox() as sandbox:
            root = sandbox.root
            sandbox.create(source)
            raise RuntimeError("boom")

    assert not root.exists()


def test_unknown_snapshot_is_an_error(source):
    with LocalSandbox() as sandbox:
        sandbox.create(source)
        base = sandbox.create(source)
        bogus = type(base)(id="does-not-exist")

        with pytest.raises(SandboxError):
            sandbox.run(bogus, "true")


def test_secrets_in_the_environment_are_not_visible_to_sandboxed_code(source, monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "super-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "also-secret")

    with LocalSandbox() as sandbox:
        result = sandbox.run(sandbox.create(source), "env")

    assert "super-secret" not in result.stdout
    assert "also-secret" not in result.stdout
