"""Live checks against Token Factory.

Run: uv run --env-file .env python scripts/spike_token_factory.py

Answers, per role: does the base URL answer, where does reasoning come back, does JSON mode
work, does tool calling work. Prints a markdown summary to paste into docs/spikes/token-factory.md.
"""

import json
import os
import time

from openai import OpenAI

from faultforge.llm import parse_json
from faultforge.llm.token_factory import TokenFactoryConfig

TOOL = {
    "type": "function",
    "function": {
        "name": "record_strategy",
        "description": "Record a repair strategy",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "summary": {"type": "string"}},
            "required": ["id", "summary"],
        },
    },
}
ASK = 'Reply with JSON only: {"strategy": "<one short sentence about idempotency keys>"}'


def check(name, fn, *args):
    started = time.monotonic()
    try:
        detail = fn(*args)
        return f"| {name} | ok | {time.monotonic() - started:.1f}s | {detail} |"
    except Exception as error:  # report every failure, keep going
        return f"| {name} | FAILED | {time.monotonic() - started:.1f}s | {str(error)[:160]} |"


def plain(client, model):
    messages = [{"role": "user", "content": ASK}]
    r = client.chat.completions.create(model=model, messages=messages, max_tokens=2048)
    m = r.choices[0].message
    reasoning = getattr(m, "reasoning_content", None)
    parsed = parse_json(m.content or "")
    return (
        f"`<think>` in content: {'<think>' in (m.content or '')}; "
        f"separate reasoning field: {bool(reasoning)}; parsed: {json.dumps(parsed)[:60]}; "
        f"tokens: {r.usage.prompt_tokens}/{r.usage.completion_tokens}"
    )


def json_mode(client, model):
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": ASK}],
        max_tokens=2048,
        response_format={"type": "json_object"},
    )
    return f"parsed: {json.dumps(parse_json(r.choices[0].message.content or ''))[:60]}"


def tools(client, model):
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Record one idempotency-key strategy."}],
        tools=[TOOL],
        max_tokens=2048,
    )
    calls = r.choices[0].message.tool_calls or []
    return f"tool calls: {[c.function.name for c in calls]}"


def main() -> None:
    config = TokenFactoryConfig.from_env(os.environ)
    routes = {
        "plan": (config.plan_base_url, config.plan_model),
        "write": (config.write_base_url, config.write_model),
    }
    rows = ["| Check | Result | Time | Detail |", "|---|---|---|---|"]
    for role, (base_url, model) in routes.items():
        client = OpenAI(base_url=base_url, api_key=config.api_key, timeout=120)
        rows.append(check(f"{role} answers ({model} @ {base_url})", plain, client, model))
        rows.append(check(f"{role} JSON mode", json_mode, client, model))
        rows.append(check(f"{role} tool calling", tools, client, model))
    print("\n".join(rows))


if __name__ == "__main__":
    main()
