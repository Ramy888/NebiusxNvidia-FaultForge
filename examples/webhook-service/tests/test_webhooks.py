import httpx

from payments.verifier import ChargeVerifier
from payments.webhooks import OrderBook, handle_payment_webhook


def provider(status: str) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        charge_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"id": charge_id, "status": status})

    return httpx.Client(transport=httpx.MockTransport(handler))


EVENT = {"type": "payment.succeeded", "data": {"charge_id": "ch_1", "order_id": "ord_1"}}


def test_verified_payment_marks_the_order_paid():
    orders = OrderBook({"ord_1": "awaiting_payment"})
    verifier = ChargeVerifier(provider("succeeded"), base_url="https://pay.test")

    handle_payment_webhook(EVENT, verifier, orders)

    assert orders.status("ord_1") == "paid"


def test_failed_charge_leaves_the_order_unpaid():
    orders = OrderBook({"ord_1": "awaiting_payment"})
    verifier = ChargeVerifier(provider("failed"), base_url="https://pay.test")

    handle_payment_webhook(EVENT, verifier, orders)

    assert orders.status("ord_1") == "awaiting_payment"


def test_other_event_types_are_ignored():
    orders = OrderBook({"ord_1": "awaiting_payment"})
    verifier = ChargeVerifier(provider("succeeded"), base_url="https://pay.test")

    handle_payment_webhook({"type": "customer.created", "data": {}}, verifier, orders)

    assert orders.status("ord_1") == "awaiting_payment"
