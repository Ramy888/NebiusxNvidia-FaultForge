import os

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
        # FAULTKIT_DISABLED=1 gives a control run: a valid failure test must pass without faults.
        faults = () if os.environ.get("FAULTKIT_DISABLED") == "1" else self._faults
        for fault in faults:
            if fault.applies(self.calls):
                return fault.apply(request, self._handler)
        response = self._handler(request)
        response.request = request
        return response
