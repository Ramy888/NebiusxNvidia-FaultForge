import json

import httpx

from orders.fulfillment import FulfillmentClient
from orders.service import OrderService


def fake_fulfillment(received: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        received.append(body)
        return httpx.Response(201, json={"id": f"ful_{len(received)}", "status": "accepted"})

    return httpx.MockTransport(handler)


def make_service(received: list[dict]) -> OrderService:
    http = httpx.Client(transport=fake_fulfillment(received))
    return OrderService(FulfillmentClient(http, base_url="https://fulfillment.test"))


def test_place_order_confirms_with_fulfillment_reference():
    received: list[dict] = []
    service = make_service(received)

    order = service.place_order("cus_1", [{"sku": "MUG-01", "qty": 2}])

    assert order.status == "confirmed"
    assert order.fulfillment_id == "ful_1"


def test_place_order_sends_items_to_fulfillment():
    received: list[dict] = []
    service = make_service(received)

    order = service.place_order("cus_1", [{"sku": "MUG-01", "qty": 2}])

    assert received == [
        {"order_id": order.id, "customer_id": "cus_1", "items": [{"sku": "MUG-01", "qty": 2}]}
    ]


def test_placed_orders_are_listed():
    service = make_service([])

    order = service.place_order("cus_1", [{"sku": "MUG-01", "qty": 1}])

    assert service.list_orders() == [order]
