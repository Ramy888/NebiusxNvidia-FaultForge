"""Order placement for the shop."""

import uuid
from dataclasses import dataclass

import httpx

from orders.fulfillment import FulfillmentClient


@dataclass(frozen=True)
class Order:
    id: str
    customer_id: str
    items: tuple
    fulfillment_id: str
    status: str


class OrderService:
    def __init__(self, fulfillment: FulfillmentClient, max_retries: int = 2):
        self._fulfillment = fulfillment
        self._max_retries = max_retries
        self._orders: list[Order] = []

    def place_order(self, customer_id: str, items: list[dict]) -> Order:
        order_id = f"ord_{uuid.uuid4().hex[:12]}"
        # The provider can be slow at peak times, so retry timed-out requests.
        for attempt in range(self._max_retries + 1):
            try:
                result = self._fulfillment.create_fulfillment(order_id, customer_id, items)
                break
            except httpx.TimeoutException:
                if attempt == self._max_retries:
                    raise
        order = Order(
            id=order_id,
            customer_id=customer_id,
            items=tuple(items),
            fulfillment_id=result["id"],
            status="confirmed",
        )
        self._orders.append(order)
        return order

    def list_orders(self) -> list[Order]:
        return list(self._orders)
