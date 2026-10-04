from types import SimpleNamespace

import pytest

from faultforge.llm import LLMError
from faultforge.llm.token_factory import TokenFactoryConfig, TokenFactoryLLM

ENV = {
    "NEBIUS_API_KEY": "key-123",
    "PLAN_BASE_URL": "https://plan.example/v1",
    "PLAN_MODEL": "nvidia/ultra",
    "WRITE_BASE_URL": "https://write.example/v1",
    "WRITE_MODEL": "nvidia/nano",
}


class FakeOpenAI:
    instances: list["FakeOpenAI"] = []

    def __init__(self, base_url: str, api_key: str, **_):
        self.base_url, self.api_key, self.requests = base_url, api_key, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        FakeOpenAI.instances.append(self)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        message = SimpleNamespace(content='{"ok": true}', reasoning_content="thinking...")
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


@pytest.fixture
def llm():
    FakeOpenAI.instances = []
    return TokenFactoryLLM(TokenFactoryConfig.from_env(ENV), client_factory=FakeOpenAI)


def test_roles_go_to_their_own_region_and_model(llm):
    llm.complete("plan", "sys", "plan this")
    llm.complete("write", "sys", "write this")

    by_url = {client.base_url: client for client in FakeOpenAI.instances}
    assert by_url["https://plan.example/v1"].requests[0]["model"] == "nvidia/ultra"
    assert by_url["https://write.example/v1"].requests[0]["model"] == "nvidia/nano"


def test_returns_content_without_reasoning(llm):
    assert llm.complete("plan", "sys", "hi") == '{"ok": true}'


def test_messages_carry_system_and_user_prompts(llm):
    llm.complete("write", "be terse", "hello")

    request = FakeOpenAI.instances[1].requests[0]
    assert request["messages"] == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hello"},
    ]


def test_token_usage_is_tracked_per_role(llm):
    llm.complete("plan", "s", "u")
    llm.complete("plan", "s", "u")

    assert llm.usage["plan"] == {"prompt_tokens": 20, "completion_tokens": 10, "calls": 2}


def test_missing_api_key_is_a_clear_error():
    with pytest.raises(LLMError, match="NEBIUS_API_KEY"):
        TokenFactoryConfig.from_env({k: v for k, v in ENV.items() if k != "NEBIUS_API_KEY"})


def test_defaults_point_at_nemotron_models():
    config = TokenFactoryConfig.from_env({"NEBIUS_API_KEY": "k"})

    assert "Nemotron-3-Ultra" in config.plan_model
    assert "Nemotron-3-Nano" in config.write_model


def test_json_mode_is_opt_in(llm):
    llm.complete("plan", "s", "u")
    assert "response_format" not in FakeOpenAI.instances[0].requests[0]

    json_llm = TokenFactoryLLM(
        TokenFactoryConfig.from_env(ENV | {"TF_JSON_MODE": "1"}), client_factory=FakeOpenAI
    )
    json_llm.complete("plan", "s", "u")
    assert FakeOpenAI.instances[-2].requests[0]["response_format"] == {"type": "json_object"}


def test_writer_thinking_is_off_and_json_mode_only_applies_to_planning():
    FakeOpenAI.instances = []
    llm = TokenFactoryLLM(
        TokenFactoryConfig.from_env(ENV | {"TF_JSON_MODE": "1"}), client_factory=FakeOpenAI
    )

    llm.complete("plan", "s", "u")
    llm.complete("write", "s", "u")

    plan_request = FakeOpenAI.instances[0].requests[0]
    write_request = FakeOpenAI.instances[1].requests[0]
    assert plan_request["response_format"] == {"type": "json_object"}
    assert "extra_body" not in plan_request
    assert "response_format" not in write_request
    assert write_request["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
