import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Event:
    seq: int
    type: str
    data: dict = field(default_factory=dict)
    ts: float = 0.0


class EventLog:
    """Append-only, thread-safe record of what a run did. CLI, API and UI all read it."""

    def __init__(self) -> None:
        self._items: list[Event] = []
        self._subscribers: list[Callable[[Event], None]] = []
        self._lock = threading.Lock()

    def emit(self, type: str, **data) -> Event:
        with self._lock:
            event = Event(seq=len(self._items), type=type, data=data, ts=time.time())
            self._items.append(event)
            subscribers = list(self._subscribers)
        for callback in subscribers:
            callback(event)
        return event

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def items(self, since: int = 0) -> list[Event]:
        with self._lock:
            return self._items[since:]
