"""Live contract check against Token Factory Sandboxes.

Runs only with FAULTFORGE_LIVE_CONTREE=1 and Contree credentials (`contree auth`).
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("FAULTFORGE_LIVE_CONTREE") != "1", reason="live Contree check is opt-in"
)


def test_upload_run_and_branch(tmp_path: Path):
    from faultforge.sandbox.contree import ContreeSandbox

    (tmp_path / "hello.txt").write_text("hello\n")
    sandbox = ContreeSandbox()
    base = sandbox.create(tmp_path)

    changed = sandbox.run(base, "echo changed > hello.txt && cat hello.txt")
    sibling = sandbox.run(base, "cat hello.txt")
    follow_up = sandbox.run(changed.snapshot, "cat hello.txt")

    assert changed.stdout == "changed\n"
    assert sibling.stdout == "hello\n"
    assert follow_up.stdout == "changed\n"
