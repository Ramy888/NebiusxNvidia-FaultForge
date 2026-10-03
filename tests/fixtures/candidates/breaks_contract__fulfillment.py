"""Client for the external fulfillment provider's HTTP API."""

import httpx


class FulfillmentClient:
    def __init__(self, http: httpx.Client, base_url: str):
        self._http = http
        self._base_url = base_url.rstrip("/")

    def create_fulfillment(self, order_id: str, customer_id: str, items: list[dict]) -> dict:
        response = self._http.post(
            f"{self._base_url}/fulfillments",
            json={"order_id": order_id, "headers": {"Idempotency-Key": order_id}, "customer_id": customer_id, "items": items},
            timeout=5.0,
        )
        response.raise_for_status()
        return response.json()
