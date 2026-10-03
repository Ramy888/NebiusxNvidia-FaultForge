"""Payment webhook handling."""

from payments.verifier import ChargeVerifier


class OrderBook:
    def __init__(self, statuses: dict[str, str]):
        self._statuses = dict(statuses)

    def status(self, order_id: str) -> str:
        return self._statuses[order_id]

    def mark_paid(self, order_id: str) -> None:
        self._statuses[order_id] = "paid"


def handle_payment_webhook(event: dict, verifier: ChargeVerifier, orders: OrderBook) -> None:
    if event.get("type") != "payment.succeeded":
        return
    data = event["data"]
    if verifier.charge_status(data["charge_id"]) == "succeeded":
        orders.mark_paid(data["order_id"])
