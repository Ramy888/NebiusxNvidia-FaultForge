"""Live web research (Tavily): how does the real dependency behave when things go wrong?"""

from dataclasses import dataclass, field

import httpx

from .events import EventLog

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class Research:
    notes: str = ""
    sources: list[Source] = field(default_factory=list)


class TavilyResearcher:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        self._api_key = api_key
        self._http = http or httpx.Client(timeout=20)

    def search(self, query: str) -> Research:
        response = self._http.post(
            TAVILY_SEARCH_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "query": query,
                "max_results": 5,
                "search_depth": "basic",
                "include_answer": True,
            },
        )
        response.raise_for_status()
        data = response.json()
        sources = [
            Source(r.get("title", ""), r.get("url", ""), (r.get("content") or "")[:400])
            for r in data.get("results", [])
        ]
        lines = [data["answer"]] if data.get("answer") else []
        lines += [f"- {s.title}: {s.snippet} ({s.url})" for s in sources]
        return Research(notes="\n".join(lines), sources=sources)


def research_dependency(researcher: TavilyResearcher | None, dependency, events: EventLog):
    if researcher is None:
        events.emit("research_skipped", reason="no TAVILY_API_KEY")
        return Research()
    query = (
        f"{dependency.name} API timeouts rate limits Retry-After retries idempotency keys "
        "duplicate requests documentation"
    )
    events.emit("research_started", query=query)
    try:
        research = researcher.search(query)
    except (httpx.HTTPError, ValueError, KeyError) as error:
        events.emit("research_failed", reason=str(error))
        return Research()
    events.emit(
        "research_finished",
        sources=[{"title": s.title, "url": s.url} for s in research.sources],
    )
    return research
