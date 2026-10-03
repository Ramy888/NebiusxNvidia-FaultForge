"""FaultForge scenario: the payment provider rate-limits the charge check."""

import httpx
from faultkit import FakeAPI, FaultyTransport, RateLimit

from payments.verifier import ChargeVerifier
from payments.webhooks import OrderBook, handle_payment_webhook

EVENT = {"type": "payment.succeeded", "data": {"charge_id": "ch_1", "order_id": "ord_1"}}


def test_rate_limited_check_never_marks_an_unverified_order_paid():
    provider = FakeAPI(status=200, body={"status": "failed"})
    transport = FaultyTransport(provider, RateLimit(on_calls={1}, retry_after=1))
    verifier = ChargeVerifier(httpx.Client(transport=transport), base_url="https://pay.test")
    orders = OrderBook({"ord_1": "awaiting_payment"})

    try:
        handle_payment_webhook(EVENT, verifier, orders)
    except Exception:
        pass  # surfacing the error so the provider redelivers the webhook is acceptable

    assert orders.status("ord_1") != "paid", (
        "order marked paid although the charge was never verified (provider answered 429)"
    )
