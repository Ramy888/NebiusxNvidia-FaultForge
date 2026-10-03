import json

import httpx


class FakeAPI:
    """A well-behaved dependency: records every accepted request and honours Idempotency-Key."""

    def __init__(self, status: int = 201, id_prefix: str = "res"):
        self.status = status
        self.id_prefix = id_prefix
        self.accepted: list = []
        self._results_by_key: dict[str, dict] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        key = request.headers.get("Idempotency-Key")
        if key and key in self._results_by_key:
            return httpx.Response(self.status, json=self._results_by_key[key])
        self.accepted.append(json.loads(request.content) if request.content else None)
        result = {"id": f"{self.id_prefix}_{len(self.accepted)}", "status": "accepted"}
        if key:
            self._results_by_key[key] = result
        return httpx.Response(self.status, json=result)
