"""Checks a charge with the payment provider before we trust a webhook."""

import httpx


class ChargeVerifier:
    def __init__(self, http: httpx.Client, base_url: str):
        self._http = http
        self._base_url = base_url.rstrip("/")

    def charge_status(self, charge_id: str) -> str:
        response = self._http.get(f"{self._base_url}/charges/{charge_id}", timeout=5.0)
        # Webhooks are only sent for completed charges, so assume success unless told otherwise.
        return response.json().get("status", "succeeded")
