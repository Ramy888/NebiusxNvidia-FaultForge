import httpx

from .faults import Fault, Handler


class FaultyTransport(httpx.BaseTransport):
    """Routes requests to an in-process dependency, injecting faults on chosen calls."""

    def __init__(self, handler: Handler, *faults: Fault):
        self._handler = handler
        self._faults = faults
        self.calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        request.read()
        for fault in self._faults:
            if fault.applies(self.calls):
                return fault.apply(request, self._handler)
        response = self._handler(request)
        response.request = request
        return response
