import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol

# "plan": deep analysis (Nemotron Ultra). "write": fast generation of tests and patches (Nano).
# "fix": a second attempt after verification failed, by the reasoning model.
Role = Literal["plan", "write", "fix"]


class LLMError(Exception):
    pass


@dataclass(frozen=True)
class Call:
    role: Role
    system: str
    user: str


class LLM(Protocol):
    def complete(self, role: Role, system: str, user: str) -> str: ...


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def parse_json(raw: str) -> dict:
    """Extract the first JSON object from model output, ignoring reasoning and code fences."""
    text = _THINK.sub("", raw)
    start = text.find("{")
    while start != -1:
        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    raise LLMError("no JSON object found in model output")
