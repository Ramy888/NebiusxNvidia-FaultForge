"""Bundled demo: the order-service example with recorded model responses for offline runs."""

from pathlib import Path

DEMO_DIR = Path(__file__).parent
REPO_ROOT = DEMO_DIR.parents[1]
ORDER_SERVICE = DEMO_DIR / "order_service"
ORDER_SERVICE_REPO = REPO_ROOT / "examples" / "order-service"
WEBHOOK_SERVICE = DEMO_DIR / "webhook_service"
WEBHOOK_SERVICE_REPO = REPO_ROOT / "examples" / "webhook-service"

# name -> (bundled demo assets, example repo)
EXAMPLES = {
    "order-service": (ORDER_SERVICE, ORDER_SERVICE_REPO),
    "webhook-service": (WEBHOOK_SERVICE, WEBHOOK_SERVICE_REPO),
}

DESCRIPTIONS = {
    "order-service": "Shop backend that places orders with a fulfillment provider and retries "
    "requests that time out.",
    "webhook-service": "Payment webhook handler that checks each charge with the payment provider "
    "before marking an order paid.",
}
