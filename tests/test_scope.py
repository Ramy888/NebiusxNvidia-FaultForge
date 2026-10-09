"""A repair may only change existing code on the dependency path.

The weakness this guards against (docs/live-runs.md, 2026-10-06): a winning webhook patch carried a
real fix plus `OrderBook.status` returning "unknown" for missing orders, which only made a broken
generated test pass. Verification accepted it because every check went green.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from faultforge.demo import ORDER_SERVICE, ORDER_SERVICE_REPO
from faultforge.discovery import CallSite, Dependency
from faultforge.events import EventLog
from faultforge.llm import StubLLM
from faultforge.pipeline import Status, run_pipeline
from faultforge.sandbox import LocalSandbox
from faultforge.scenarios import scenario_from_file
from faultforge.scope import changed_functions, off_path_changes

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
REPLAYS = ROOT / "web" / "replays"


def dependency(operation: str, *call_sites: str) -> Dependency:
    sites = []
    for ref in call_sites:
        path, function = ref.split(":")
        sites.append(CallSite(path=path, line=1, function=function, method="get", target=""))
    return Dependency(name="dep", operation=operation, notes="", call_sites=sites)


WEBHOOK = dependency(
    "payments.webhooks:handle_payment_webhook", "payments/verifier.py:ChargeVerifier.charge_status"
)
ORDERS = dependency(
    "orders.service:OrderService.place_order",
    "orders/fulfillment.py:FulfillmentClient.create_fulfillment",
)


def read(repo: Path, path: str) -> str:
    return (repo / path).read_text()


def edit(code: str, old: str, new: str) -> str:
    assert old in code, f"fixture drifted: {old!r} not found"
    return code.replace(old, new)


# --- changed_functions ---------------------------------------------------------------------------


def test_reports_modified_existing_functions_only():
    old = "def a():\n    return 1\n\ndef b():\n    return 2\n"
    new = (
        "import os\n\ndef a():\n    return 1\n\ndef b():\n    return 3\n\ndef helper():\n    pass\n"
    )

    assert changed_functions({"m.py": old}, {"m.py": new}) == {"m.py:b"}


def test_ignores_comment_and_formatting_changes():
    old = "def a(x):\n    return x+1\n"
    new = "def a(x):\n    # explain\n    return x + 1\n"

    assert changed_functions({"m.py": old}, {"m.py": new}) == set()


def test_reports_methods_with_their_class_and_removed_functions():
    old = "class K:\n    def m(self):\n        return 1\n\ndef gone():\n    pass\n"
    new = "class K:\n    def m(self):\n        return 2\n"

    assert changed_functions({"m.py": old}, {"m.py": new}) == {"m.py:K.m", "m.py:gone"}


def test_new_files_are_not_changes():
    assert changed_functions({}, {"new.py": "def a():\n    pass\n"}) == set()


# --- the documented weakness ---------------------------------------------------------------------


def webhook_patch(with_status_hack: bool) -> dict[str, str]:
    repo = EXAMPLES / "webhook-service"
    verifier = read(repo, "payments/verifier.py")
    patch = {"payments/verifier.py": edit(verifier, *_real_fix_for(verifier))}
    if with_status_hack:
        webhooks = read(repo, "payments/webhooks.py")
        patch["payments/webhooks.py"] = edit(
            webhooks,
            "return self._statuses[order_id]",
            'return self._statuses.get(order_id, "unknown")',
        )
    return patch


def _real_fix_for(verifier: str) -> tuple[str, str]:
    # insert a status check before the response body is read, as the genuine winners did
    line = next(ln for ln in verifier.splitlines() if "response.json()" in ln)
    indent = line[: len(line) - len(line.lstrip())]
    return line, f"{indent}response.raise_for_status()\n{line}"


def test_rejects_the_documented_orderbook_status_hack():
    repo = EXAMPLES / "webhook-service"
    patch = webhook_patch(with_status_hack=True)
    original = {p: read(repo, p) for p in patch}

    assert off_path_changes(original, patch, WEBHOOK, repo) == [
        "payments/webhooks.py:OrderBook.status"
    ]


def test_accepts_the_same_real_fix_on_its_own():
    repo = EXAMPLES / "webhook-service"
    patch = webhook_patch(with_status_hack=False)
    original = {p: read(repo, p) for p in patch}

    assert off_path_changes(original, patch, WEBHOOK, repo) == []


def test_changing_a_function_the_operation_never_reaches_is_off_path():
    repo = ORDER_SERVICE_REPO
    service = read(repo, "orders/service.py")
    patch = {
        "orders/service.py": edit(
            service, "return list(self._orders)", "return list(self._orders)[:]"
        )
    }

    assert off_path_changes({"orders/service.py": service}, patch, ORDERS, repo) == [
        "orders/service.py:OrderService.list_orders"
    ]


def test_unresolvable_dependency_skips_the_guard():
    repo = ORDER_SERVICE_REPO
    service = read(repo, "orders/service.py")
    patch = {"orders/service.py": edit(service, "return list(self._orders)", "return []")}
    unknown = dependency("nowhere:missing", "nope.py:missing")

    assert off_path_changes({"orders/service.py": service}, patch, unknown, repo) == []


# --- every genuine winner recorded live must still be accepted -----------------------------------


def apply_diff(repo: Path, diff: str, tmp_path: Path) -> dict[str, str]:
    work = tmp_path / "repo"
    shutil.copytree(repo, work, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
    subprocess.run(["patch", "-p1", "-s"], input=diff, text=True, cwd=work, check=True)
    changed = [ln[6:] for ln in diff.splitlines() if ln.startswith("+++ b/")]
    return {p: (work / p).read_text() for p in changed}


RECORDED = ["hook-slinger", "order-service", "webhook-service"]  # web/replays/<name>.json


@pytest.mark.skipif(shutil.which("patch") is None, reason="needs the patch tool")
@pytest.mark.parametrize("name", RECORDED)
def test_recorded_live_winners_stay_on_the_dependency_path(name, tmp_path):
    result = json.loads((REPLAYS / f"{name}.json").read_text())["result"]
    dep = result["dependency"]
    found = dependency(dep["operation"], *dep["call_sites"])
    winner = next(c for c in result["candidates"] if c["accepted"])
    repo = EXAMPLES / name
    patched = apply_diff(repo, winner["diff"], tmp_path)
    original = {p: read(repo, p) for p in patched if (repo / p).exists()}

    assert off_path_changes(original, patched, found, repo) == []


def test_hosted_live_winner_of_2026_10_09_stays_on_path():
    # run 50ec3c462011 on the Cloudflare demo: a one-line Idempotency-Key header
    repo = ORDER_SERVICE_REPO
    client = read(repo, "orders/fulfillment.py")
    patch = {
        "orders/fulfillment.py": edit(
            client,
            "            timeout=5.0,",
            '            headers={"Idempotency-Key": order_id},\n            timeout=5.0,',
        )
    }

    assert off_path_changes({"orders/fulfillment.py": client}, patch, ORDERS, repo) == []


# --- end to end: an off-path change loses its win ------------------------------------------------


def stub_with_off_path_change() -> StubLLM:
    recorded = json.loads((ORDER_SERVICE / "llm_responses.json").read_text())
    first = json.loads(recorded["write"][0])
    service = read(ORDER_SERVICE_REPO, "orders/service.py")
    first["files"]["orders/service.py"] = edit(
        service, "return list(self._orders)", "return list(self._orders)[:]"
    )
    return StubLLM(plan=recorded["plan"], write=[json.dumps(first), *recorded["write"][1:]])


def run_with(dep):
    with LocalSandbox() as sandbox:
        return run_pipeline(
            ORDER_SERVICE_REPO,
            [scenario_from_file(ORDER_SERVICE / "scenarios" / "timeout_duplicate.py")],
            stub_with_off_path_change(),
            sandbox,
            EventLog(),
            dependency=dep,
        )


def test_pipeline_rejects_a_winner_that_changes_code_off_the_dependency_path():
    result = run_with(ORDERS)

    rejected = next(r for r in result.report.results if r.candidate.id == "idempotency_key")
    assert "OrderService.list_orders" in rejected.rejection_reason
    assert "dependency path" in rejected.rejection_reason
    assert result.status is Status.NO_REPAIR


def test_without_a_known_dependency_the_same_candidate_still_wins():
    result = run_with(None)

    assert result.status is Status.REPAIRED
    assert result.winner.candidate.id == "idempotency_key"


# --- review findings (2026-10-09) ----------------------------------------------------------------


def write_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for path, code in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(code)
    return tmp_path


def test_a_patch_cannot_put_its_own_off_path_change_on_the_path(tmp_path):
    repo = EXAMPLES / "webhook-service"
    patch = webhook_patch(with_status_hack=True)
    # the same hack, plus a harmless new reference to OrderBook.status from the operation
    webhooks = patch["payments/webhooks.py"]
    patch["payments/webhooks.py"] = edit(
        webhooks,
        '    if event.get("type") != "payment.succeeded":',
        '    orders.status(event.get("id", ""))\n    if event.get("type") != "payment.succeeded":',
    )
    original = {p: read(repo, p) for p in patch}

    assert "payments/webhooks.py:OrderBook.status" in off_path_changes(
        original, patch, WEBHOOK, repo
    )


def test_a_changed_property_getter_is_seen_next_to_its_setter():
    old = (
        "class K:\n    @property\n    def v(self):\n        return 1\n\n"
        "    @v.setter\n    def v(self, x):\n        pass\n"
    )
    new = old.replace("return 1", "return 2")

    assert changed_functions({"m.py": old}, {"m.py": new}) == {"m.py:K.v"}


def test_docstring_only_edits_are_not_changes():
    old = 'def a():\n    """Old."""\n    return 1\n'
    new = 'def a():\n    """New wording."""\n    return 1\n'

    assert changed_functions({"m.py": old}, {"m.py": new}) == set()


CLIENT = """class Client:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def unrelated(self):
        return 1


def call(url):
    with Client() as c:
        return url
"""


def test_implicit_dunder_methods_of_a_reached_class_are_on_the_path(tmp_path):
    repo = write_repo(tmp_path, {"app/client.py": CLIENT})
    dep = dependency("app.client:call", "app/client.py:call")
    patch = {"app/client.py": CLIENT.replace("return False", "return None")}

    assert off_path_changes({"app/client.py": CLIENT}, patch, dep, repo) == []
    patch = {"app/client.py": CLIENT.replace("return 1", "return 2")}
    assert off_path_changes({"app/client.py": CLIENT}, patch, dep, repo) == [
        "app/client.py:Client.unrelated"
    ]


def test_import_aliases_resolve_to_the_imported_function(tmp_path):
    files = {
        "app/checks.py": "def verify(x):\n    return x\n",
        "app/handler.py": (
            "from app.checks import verify as check\n\n\ndef handle(x):\n    return check(x)\n"
        ),
    }
    repo = write_repo(tmp_path, files)
    dep = dependency("app.handler:handle", "app/handler.py:handle")
    patch = {"app/checks.py": "def verify(x):\n    return bool(x)\n"}

    assert off_path_changes({"app/checks.py": files["app/checks.py"]}, patch, dep, repo) == []


def test_nested_call_sites_and_src_layouts_resolve(tmp_path):
    code = (
        "def outer():\n    def _send():\n        return 1\n    return _send()\n\n\n"
        "def other():\n    return 2\n"
    )
    repo = write_repo(tmp_path, {"src/app/svc.py": code})
    dep = dependency("app.svc:outer", "src/app/svc.py:outer._send")
    patch = {"src/app/svc.py": code.replace("return 2", "return 3")}

    assert off_path_changes({"src/app/svc.py": code}, patch, dep, repo) == ["src/app/svc.py:other"]
