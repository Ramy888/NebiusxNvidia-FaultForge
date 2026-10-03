"""FaultForge scenario: the provider accepts an order but the response times out."""

import httpx
from faultkit import FakeAPI, FaultyTransport, Timeout

from orders.fulfillment import FulfillmentClient
from orders.service import OrderService


def test_one_order_creates_one_fulfillment_when_response_times_out():
    provider = FakeAPI(id_prefix="ful")
    transport = FaultyTransport(provider, Timeout(on_calls={1}, after_processing=True))
    http = httpx.Client(transport=transport)
    service = OrderService(FulfillmentClient(http, base_url="https://fulfillment.test"))

    order = service.place_order("cus_1", [{"sku": "MUG-01", "qty": 1}])

    assert len(provider.accepted) == 1, (
        f"one order created {len(provider.accepted)} fulfillments at the provider"
    )
    assert order.status == "confirmed"
