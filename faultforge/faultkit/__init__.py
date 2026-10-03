"""Deterministic HTTP dependency faults for httpx clients.

This package is copied verbatim into the code under test, so it must only depend on httpx.
"""

from .api import FakeAPI
from .faults import DuplicateDelivery, Fault, Malformed, RateLimit, Timeout
from .transport import FaultyTransport

__all__ = [
    "DuplicateDelivery",
    "FakeAPI",
    "Fault",
    "FaultyTransport",
    "Malformed",
    "RateLimit",
    "Timeout",
]
