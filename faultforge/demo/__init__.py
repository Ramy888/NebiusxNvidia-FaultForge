"""Bundled demo: the order-service example with recorded model responses for offline runs."""

from pathlib import Path

DEMO_DIR = Path(__file__).parent
REPO_ROOT = DEMO_DIR.parents[1]
ORDER_SERVICE = DEMO_DIR / "order_service"
ORDER_SERVICE_REPO = REPO_ROOT / "examples" / "order-service"
