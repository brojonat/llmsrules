"""A provider-agnostic streaming chat client (from ~/projects/nhtsa/src/nhtsa/llm.py).

Speaks the OpenAI Chat Completions wire format (`POST {base}/chat/completions`
with `stream: true`), which OpenRouter, OpenAI, and most local servers
(vLLM, Ollama, llama.cpp) implement. No SDK: one httpx request, and the SSE
lines parsed by hand. Trimmed to streaming text; nhtsa's copy also handles
tool calls and reasoning blocks, for when this project needs them.

Config from the environment (same names as nhtsa, so one .env serves both):
  LLM_BASE_URL   default https://openrouter.ai/api/v1
  LLM_API_KEY    falls back to OPENROUTER_API_KEY, then OPENAI_API_KEY
  LLM_MODEL      default anthropic/claude-haiku-4.5
  LLM_MAX_TOKENS per reply, default 4096
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"


@dataclass(frozen=True)
class LLMConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_MODEL
    max_tokens: int = 4096

    @classmethod
    def from_env(cls) -> LLMConfig:
        env = os.environ.get
        return cls(
            base_url=env("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            api_key=env("LLM_API_KEY") or env("OPENROUTER_API_KEY") or env("OPENAI_API_KEY") or "",
            model=env("LLM_MODEL", DEFAULT_MODEL),
            max_tokens=int(env("LLM_MAX_TOKENS", "4096")),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


@dataclass
class Delta:
    text: str


@dataclass
class Usage:
    prompt_tokens: int
    completion_tokens: int
    cost: float | None = None  # USD, when the provider reports it (OpenRouter does)


class LLMError(Exception):
    pass


async def stream_chat(http: httpx.AsyncClient, cfg: LLMConfig, messages: list[dict]) -> AsyncIterator[Delta | Usage]:
    """Yield text deltas as they arrive, then usage if the provider reports it."""
    payload = {
        "model": cfg.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": cfg.max_tokens,
    }
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Accept": "text/event-stream"}
    async with http.stream("POST", f"{cfg.base_url}/chat/completions", json=payload, headers=headers) as r:
        if r.status_code != 200:
            body = (await r.aread()).decode(errors="replace")
            raise LLMError(f"{cfg.base_url} answered {r.status_code}: {_error_message(body)}")
        async for line in r.aiter_lines():
            # SSE: "data: {...}" events; ":" lines are keep-alive comments
            # (OpenRouter sends ": OPENROUTER PROCESSING" while it waits).
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            if "error" in chunk:  # providers can fail mid-stream, after a 200
                raise LLMError(_error_message(json.dumps(chunk)))
            for choice in chunk.get("choices") or []:
                if text := (choice.get("delta") or {}).get("content"):
                    yield Delta(text)
            if usage := chunk.get("usage"):
                yield Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), usage.get("cost"))


def _error_message(body: str) -> str:
    try:
        err = json.loads(body).get("error", {})
        return err.get("message", body) if isinstance(err, dict) else str(err)
    except (ValueError, AttributeError):
        return body[:300]
