"""Nemotron on Nebius Token Factory through its OpenAI-compatible API.

Nemotron models are region-scoped, so the planning (Ultra) and writing (Nano) roles each get
their own client. Base URLs and model IDs come from the environment; verify them in the
Token Factory console.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from openai import OpenAI

from .base import LLMError, Role

DEFAULT_PLAN_BASE_URL = "https://api.tokenfactory.us-central1.nebius.com/v1"
DEFAULT_PLAN_MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b"
DEFAULT_WRITE_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
DEFAULT_WRITE_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
REASONING_MAX_TOKENS = 16384


@dataclass(frozen=True)
class TokenFactoryConfig:
    api_key: str
    plan_base_url: str
    plan_model: str
    write_base_url: str
    write_model: str
    json_mode: bool = False
    # Nemotron Nano reasons by default; for writing code it mostly costs time and tokens.
    write_thinking: bool = False
    temperature: float = 0.2
    max_tokens: int = 8192
    timeout_s: float = 180

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "TokenFactoryConfig":
        api_key = env.get("NEBIUS_API_KEY", "")
        if not api_key:
            raise LLMError("NEBIUS_API_KEY is not set; live mode needs a Token Factory API key")
        return cls(
            api_key=api_key,
            plan_base_url=env.get("PLAN_BASE_URL") or DEFAULT_PLAN_BASE_URL,
            plan_model=env.get("PLAN_MODEL") or DEFAULT_PLAN_MODEL,
            write_base_url=env.get("WRITE_BASE_URL") or DEFAULT_WRITE_BASE_URL,
            write_model=env.get("WRITE_MODEL") or DEFAULT_WRITE_MODEL,
            json_mode=env.get("TF_JSON_MODE", "") in ("1", "true", "yes"),
            write_thinking=env.get("TF_WRITE_THINKING", "") in ("1", "true", "yes"),
        )


class TokenFactoryLLM:
    def __init__(self, config: TokenFactoryConfig, client_factory: Callable = OpenAI):
        self._config = config
        self._routes = {
            "plan": (
                client_factory(
                    base_url=config.plan_base_url, api_key=config.api_key, timeout=config.timeout_s
                ),
                config.plan_model,
            ),
            "write": (
                client_factory(
                    base_url=config.write_base_url, api_key=config.api_key, timeout=config.timeout_s
                ),
                config.write_model,
            ),
        }
        # Escalation: when the fast writer's attempt fails verification, the reasoning model
        # (with its reasoning on) writes the fix.
        self._routes["fix"] = self._routes["plan"]
        self.usage = {
            role: {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0} for role in self._routes
        }

    def complete(self, role: Role, system: str, user: str) -> str:
        client, model = self._routes[role]
        request = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self._config.temperature,
            # Reasoning output counts against max_tokens, so the reasoning roles get more room.
            "max_tokens": self._config.max_tokens if role == "write" else REASONING_MAX_TOKENS,
        }
        # Only the planning role answers in JSON; the writer answers with code blocks.
        if self._config.json_mode and role == "plan":
            request["response_format"] = {"type": "json_object"}
        if role == "write" and not self._config.write_thinking:
            request["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        try:
            response = client.chat.completions.create(**request)
        except Exception as error:  # the SDK raises many transport/HTTP error types
            raise LLMError(f"Token Factory {role} call failed: {error}") from error
        self._record(role, response)
        # Reasoning (if the model returns it separately) is deliberately dropped.
        return response.choices[0].message.content or ""

    def _record(self, role: Role, response) -> None:
        usage = self.usage[role]
        usage["calls"] += 1
        if response.usage:
            usage["prompt_tokens"] += response.usage.prompt_tokens or 0
            usage["completion_tokens"] += response.usage.completion_tokens or 0
