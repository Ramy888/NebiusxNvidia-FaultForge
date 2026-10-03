from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

Handler = Callable[[httpx.Request], httpx.Response]


@dataclass
class Fault:
    """Applies to the 1-based call numbers in `on_calls`."""

    on_calls: set[int] = field(default_factory=lambda: {1})

    def applies(self, call: int) -> bool:
        return call in self.on_calls

    def apply(self, request: httpx.Request, handler: Handler) -> httpx.Response:
        raise NotImplementedError


@dataclass
class Timeout(Fault):
    """The response never arrives. With after_processing, the dependency did the work first."""

    after_processing: bool = True

    def apply(self, request, handler):
        if not self.after_processing:
            raise httpx.ConnectTimeout("connect timed out (injected)", request=request)
        handler(request)
        raise httpx.ReadTimeout("read timed out (injected)", request=request)


@dataclass
class RateLimit(Fault):
    retry_after: int = 1

    def apply(self, request, handler):
        return httpx.Response(
            429,
            headers={"Retry-After": str(self.retry_after)},
            json={"error": "rate_limited"},
            request=request,
        )


@dataclass
class Malformed(Fault):
    """The dependency did the work but the response body is truncated."""

    body: bytes = b'{"id": "res_'

    def apply(self, request, handler):
        handler(request)
        return httpx.Response(
            200, content=self.body, headers={"Content-Type": "application/json"}, request=request
        )


@dataclass
class DuplicateDelivery(Fault):
    """The request reaches the dependency twice, as with a retrying proxy."""

    def apply(self, request, handler):
        handler(request)
        return handler(request)
