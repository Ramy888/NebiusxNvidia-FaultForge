from .base import Call, LLMError, Role


class StubLLM:
    """Returns canned outputs per role, in order, and records every call."""

    def __init__(self, plan: list[str] | None = None, write: list[str] | None = None):
        self._queues: dict[str, list[str]] = {"plan": list(plan or []), "write": list(write or [])}
        self.calls: list[Call] = []

    def complete(self, role: Role, system: str, user: str) -> str:
        self.calls.append(Call(role, system, user))
        if not self._queues[role]:
            raise LLMError(f"stub has no more '{role}' responses")
        return self._queues[role].pop(0)
