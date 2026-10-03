import json

import httpx

from faultforge.auto import auto_scenarios
from faultforge.demo import ORDER_SERVICE_REPO
from faultforge.discovery import CallSite, Dependency
from faultforge.events import EventLog
from faultforge.llm import StubLLM
from faultforge.research import TavilyResearcher, research_dependency
from tests.test_scenarios import GOOD_FILL

DEPENDENCY = Dependency(
    name="Stripe payments API",
    operation="billing:charge",
    notes="",
    call_sites=[CallSite("billing.py", 3, "charge", "post", "url")],
)
TAVILY_REPLY = {
    "answer": "Stripe supports idempotency keys on POST requests.",
    "results": [
        {
            "title": "Idempotent requests",
            "url": "https://docs.stripe.com/api/idempotent_requests",
            "content": "Send an Idempotency-Key header to safely retry requests.",
        }
    ],
}


def researcher(handler) -> TavilyResearcher:
    return TavilyResearcher("tvly-test", http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_research_queries_tavily_about_the_dependency():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=TAVILY_REPLY)

    research = research_dependency(researcher(handler), DEPENDENCY, EventLog())

    body = json.loads(seen[0].content)
    assert seen[0].url == "https://api.tavily.com/search"
    assert seen[0].headers["Authorization"] == "Bearer tvly-test"
    assert "Stripe payments API" in body["query"]
    assert research.sources[0].url == "https://docs.stripe.com/api/idempotent_requests"
    assert "idempotency keys" in research.notes


def test_research_failure_does_not_stop_the_run():
    events = EventLog()

    research = research_dependency(
        researcher(lambda request: httpx.Response(401, json={"detail": "bad key"})),
        DEPENDENCY,
        events,
    )

    assert research.notes == "" and research.sources == []
    assert events.items()[-1].type == "research_failed"


def test_research_timeout_does_not_stop_the_run():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    research = research_dependency(researcher(handler), DEPENDENCY, EventLog())

    assert research.sources == []


def test_no_researcher_means_research_is_skipped():
    events = EventLog()

    research_dependency(None, DEPENDENCY, events)

    assert events.items()[-1].type == "research_skipped"


def test_auto_mode_discovers_researches_and_generates():
    analysis = json.dumps(
        {
            "dependencies": [
                {
                    "name": "fulfillment provider",
                    "call_site": "orders/fulfillment.py:FulfillmentClient.create_fulfillment",
                    "operation": "orders.service:OrderService.place_order",
                    "notes": "",
                }
            ]
        }
    )
    plan = json.dumps({"scenarios": [{"fault": "timeout", "invariant": "one fulfillment"}]})
    llm = StubLLM(plan=[analysis, plan], write=[GOOD_FILL])

    found = auto_scenarios(
        llm,
        ORDER_SERVICE_REPO,
        researcher(lambda request: httpx.Response(200, json=TAVILY_REPLY)),
        EventLog(),
    )

    assert found.dependency.name == "fulfillment provider"
    assert found.research.sources
    assert [s.fault for s in found.scenarios] == ["timeout"]
    assert "Stripe supports idempotency keys" in llm.calls[1].user


def test_report_lists_the_dependency_and_research_sources():
    from faultforge.auto import AutoScenarios
    from faultforge.report import render_markdown
    from faultforge.research import Research, Source
    from tests.test_pipeline import run_demo

    found = AutoScenarios(
        dependency=DEPENDENCY,
        research=Research("notes", [Source("Idempotent requests", "https://docs.example", "x")]),
    )

    markdown = render_markdown(run_demo(), found)

    assert "Stripe payments API" in markdown
    assert "[Idempotent requests](https://docs.example)" in markdown


def test_cli_without_scenarios_runs_auto_mode(tmp_path, monkeypatch):
    from faultforge.cli import main

    analysis = json.dumps(
        {
            "dependencies": [
                {
                    "name": "fulfillment provider",
                    "call_site": "orders/fulfillment.py:FulfillmentClient.create_fulfillment",
                    "operation": "orders.service:OrderService.place_order",
                    "notes": "",
                }
            ]
        }
    )
    plan = json.dumps({"scenarios": [{"fault": "timeout", "invariant": "one fulfillment"}]})
    recorded = json.loads(
        (
            ORDER_SERVICE_REPO.parents[1]
            / "faultforge"
            / "demo"
            / "order_service"
            / "llm_responses.json"
        ).read_text()
    )
    stub = tmp_path / "stub.json"
    stub.write_text(
        json.dumps(
            {"plan": [analysis, plan] + recorded["plan"], "write": [GOOD_FILL] + recorded["write"]}
        )
    )
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    out = tmp_path / "report.md"

    assert main(["run", str(ORDER_SERVICE_REPO), "--stub", str(stub), "--out", str(out)]) == 0
    assert "fulfillment provider" in out.read_text()
