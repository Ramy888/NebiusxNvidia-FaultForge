import json
from pathlib import Path

from faultforge.demo import ORDER_SERVICE_REPO
from faultforge.discovery import discover, find_http_call_sites
from faultforge.events import EventLog
from faultforge.llm import StubLLM

ANALYSIS = json.dumps(
    {
        "dependencies": [
            {
                "name": "fulfillment provider",
                "call_site": "orders/fulfillment.py:FulfillmentClient.create_fulfillment",
                "operation": "orders.service:OrderService.place_order",
                "notes": "retries on timeout without an idempotency key",
            }
        ]
    }
)


def test_finds_the_fulfillment_call_without_hints():
    sites = find_http_call_sites(ORDER_SERVICE_REPO)

    assert [(s.path, s.function, s.method) for s in sites] == [
        ("orders/fulfillment.py", "FulfillmentClient.create_fulfillment", "post")
    ]


def test_call_sites_in_tests_are_ignored():
    sites = find_http_call_sites(ORDER_SERVICE_REPO)

    assert not any(s.path.startswith("tests/") for s in sites)


def test_files_that_do_not_import_httpx_are_ignored(tmp_path: Path):
    (tmp_path / "app.py").write_text("def f(d):\n    return d.get('x')\n")

    assert find_http_call_sites(tmp_path) == []


def test_module_level_httpx_calls_are_found(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "import httpx\n\ndef ping():\n    return httpx.get('https://status.example')\n"
    )

    [site] = find_http_call_sites(tmp_path)

    assert (site.function, site.method, site.target) == ("ping", "get", "'https://status.example'")


def test_reasoning_model_names_dependency_and_operation():
    llm = StubLLM(plan=[ANALYSIS])

    [dependency] = discover(llm, ORDER_SERVICE_REPO, EventLog())

    assert dependency.name == "fulfillment provider"
    assert dependency.operation == "orders.service:OrderService.place_order"
    assert dependency.call_sites[0].function == "FulfillmentClient.create_fulfillment"
    assert "create_fulfillment" in llm.calls[0].user


def test_dependency_pointing_at_an_unknown_call_site_is_dropped():
    bogus = json.loads(ANALYSIS)
    bogus["dependencies"][0]["call_site"] = "nowhere.py:nothing"
    llm = StubLLM(plan=[json.dumps(bogus)])

    assert discover(llm, ORDER_SERVICE_REPO, EventLog()) == []


def test_repo_without_http_dependency_reports_nothing_without_calling_the_model(tmp_path):
    (tmp_path / "app.py").write_text("def add(a, b):\n    return a + b\n")
    llm = StubLLM()
    events = EventLog()

    assert discover(llm, tmp_path, events) == []
    assert llm.calls == []
    assert events.items()[-1].type == "no_dependencies"
