import json

import httpx


class FakeAPI:
    """A well-behaved dependency: records every accepted request and honours Idempotency-Key."""

    def __init__(self, status: int = 201, id_prefix: str = "res", body: dict | None = None):
        self.status = status
        self.id_prefix = id_prefix
        self.body = body or {}
        self.accepted: list = []
        self._results_by_key: dict[str, dict] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        key = request.headers.get("Idempotency-Key")
        if key and key in self._results_by_key:
            return httpx.Response(self.status, json=self._results_by_key[key])
        self.accepted.append(_body(request))
        result = {
            "id": f"{self.id_prefix}_{len(self.accepted)}",
            "status": "accepted",
            **self.body,
        }
        if key:
            self._results_by_key[key] = result
        return httpx.Response(self.status, json=result)


def _body(request: httpx.Request):
    if not request.content:
        return None
    try:
        return json.loads(request.content)
    except ValueError:
        return request.content.decode(errors="replace")
