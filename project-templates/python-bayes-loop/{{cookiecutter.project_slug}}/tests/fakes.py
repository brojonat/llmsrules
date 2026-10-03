"""A fake OpenAI-compatible endpoint (httpx.MockTransport), so tests need no API key."""

import json

import httpx

from {{cookiecutter.package_name}}.llm import LLMConfig


def sse(chunks: list[str]) -> bytes:
    """A Chat Completions stream: one content delta per chunk, usage, then [DONE]."""
    events = [{"choices": [{"delta": {"content": c}}]} for c in chunks]
    events.append({"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.0001}})
    lines = [": OPENROUTER PROCESSING"] + [f"data: {json.dumps(e)}" for e in events] + ["data: [DONE]"]
    return ("\n\n".join(lines) + "\n\n").encode()


def fake_llm(chunks: list[str], status: int = 200) -> tuple[httpx.AsyncClient, LLMConfig, list[dict]]:
    """(http client, config, requests seen) for a provider that streams `chunks`."""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "No auth credentials found"}})
        return httpx.Response(200, content=sse(chunks), headers={"content-type": "text/event-stream"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return http, LLMConfig(base_url="http://llm.test/v1", api_key="test-key", model="fake/model"), seen
