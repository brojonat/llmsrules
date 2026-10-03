"""A provider-agnostic streaming chat client.

Speaks the OpenAI Chat Completions wire format (`POST {base}/chat/completions`
with `stream: true`), which OpenRouter, OpenAI, and most local servers
(vLLM, Ollama, llama.cpp) implement. No SDK: one httpx request, and the SSE
lines parsed by hand.

Config from the environment:
  LLM_BASE_URL         default https://openrouter.ai/api/v1
  LLM_API_KEY          falls back to OPENROUTER_API_KEY, then OPENAI_API_KEY
  LLM_MODEL            default anthropic/claude-haiku-4.5
  LLM_CONTEXT_WINDOW   tokens; looked up from {base}/models when unset
  LLM_MAX_TOKENS       per model turn, default 4096
  LLM_MAX_CONCURRENT   in-flight requests across all users, default 8
  LLM_PROMPT_CACHE     mark the system prompt cacheable (Anthropic-style
                       cache_control); default on for anthropic/* models
  LLM_REASONING_TOKENS thinking budget per model turn, on top of
                       LLM_MAX_TOKENS; 0 (default) = no reasoning
  LLM_DAILY_TOKENS     chat stops taking messages once today's (UTC) prompt +
                       completion tokens reach this; default 10M, 0 = no limit
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
    context_window: int = 0  # 0 = unknown; ask the provider
    max_tokens: int = 4096
    max_concurrent: int = 8
    prompt_cache: bool = False
    reasoning_tokens: int = 0  # thinking budget per model turn; 0 = off
    daily_tokens: int = 10_000_000  # budget per UTC day, all users; 0 = unlimited

    @classmethod
    def from_env(cls) -> LLMConfig:
        env = os.environ.get
        model = env("LLM_MODEL", DEFAULT_MODEL)
        cache = env("LLM_PROMPT_CACHE", "auto").lower()
        return cls(
            base_url=env("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            api_key=env("LLM_API_KEY") or env("OPENROUTER_API_KEY") or env("OPENAI_API_KEY") or "",
            model=model,
            context_window=int(env("LLM_CONTEXT_WINDOW", "0")),
            max_tokens=int(env("LLM_MAX_TOKENS", "4096")),
            max_concurrent=int(env("LLM_MAX_CONCURRENT", "8")),
            reasoning_tokens=int(env("LLM_REASONING_TOKENS", "0")),
            daily_tokens=int(env("LLM_DAILY_TOKENS", "10000000")),
            prompt_cache=cache in ("1", "true", "yes", "on") or (cache == "auto" and model.startswith("anthropic/")),
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
    cached_tokens: int = 0  # prompt tokens served from the provider's cache


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text, as the model wrote it

    def to_api(self) -> dict:
        return {"id": self.id, "type": "function", "function": {"name": self.name, "arguments": self.arguments}}


@dataclass
class Reasoning:
    """The model's thinking blocks for this turn (OpenRouter `reasoning_details`),
    reassembled from the stream. They go back with the assistant message:
    Anthropic needs them to continue a tool-use turn."""

    details: list[dict]


@dataclass
class ToolCalls:
    """The model asked for these tools; it yields after the text, at the end of the turn."""

    calls: list[ToolCall]


class LLMError(Exception):
    pass


async def stream_chat(
    http: httpx.AsyncClient, cfg: LLMConfig, messages: list[dict], tools: list[dict] | None = None
) -> AsyncIterator[Delta | Reasoning | ToolCalls | Usage]:
    """Yield text deltas as they arrive, usage if the provider reports it, then
    the turn's reasoning (if any) and, if the model called tools, one
    ToolCalls with them reassembled."""
    if cfg.prompt_cache and messages and messages[0]["role"] == "system":
        # The system prompt is identical across users and turns: let the
        # provider cache it. Reads then cost ~10% of normal input.
        system = {"type": "text", "text": messages[0]["content"], "cache_control": {"type": "ephemeral"}}
        messages = [{"role": "system", "content": [system]}, *messages[1:]]
    payload = {
        "model": cfg.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": cfg.max_tokens + cfg.reasoning_tokens,
    }
    if cfg.reasoning_tokens:
        # The budget comes out of max_tokens, hence the sum above: the reply
        # keeps its full LLM_MAX_TOKENS.
        payload["reasoning"] = {"max_tokens": cfg.reasoning_tokens}
    if tools:
        payload["tools"] = tools
    # Tool calls stream as fragments keyed by index: the id and name first,
    # then the arguments JSON a few characters at a time.
    calls: dict[int, ToolCall] = {}
    thinking: dict[int, dict] = {}  # reasoning_details fragments, merged by index
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
                delta = choice.get("delta") or {}
                if text := delta.get("content"):
                    yield Delta(text)
                for frag in delta.get("reasoning_details") or []:
                    _merge_reasoning(thinking.setdefault(frag.get("index", 0), {}), frag)
                for frag in delta.get("tool_calls") or []:
                    call = calls.setdefault(frag.get("index", 0), ToolCall("", "", ""))
                    call.id = frag.get("id") or call.id
                    fn = frag.get("function") or {}
                    call.name = fn.get("name") or call.name
                    call.arguments += fn.get("arguments") or ""
            if usage := chunk.get("usage"):
                cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
                yield Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), usage.get("cost"), cached)
    if thinking:
        yield Reasoning([thinking[i] for i in sorted(thinking)])
    if calls:
        yield ToolCalls([calls[i] for i in sorted(calls)])


def _merge_reasoning(block: dict, frag: dict) -> None:
    """Text arrives a few tokens at a time; the signature etc. once, at the end."""
    for k, v in frag.items():
        if k in ("text", "summary", "data") and isinstance(v, str):
            block[k] = block.get(k, "") + v
        elif v is not None:
            block[k] = v


async def context_window(http: httpx.AsyncClient, cfg: LLMConfig) -> int:
    """The model's context length from the provider's model list, 0 if unknown.
    OpenRouter reports `context_length`; others may not list it at all."""
    if cfg.context_window:
        return cfg.context_window
    try:
        r = await http.get(f"{cfg.base_url}/models", headers={"Authorization": f"Bearer {cfg.api_key}"})
        r.raise_for_status()
        for m in r.json().get("data", []):
            if m.get("id") == cfg.model:
                return int(m.get("context_length") or m.get("context_window") or 0)
    except (httpx.HTTPError, ValueError):
        pass
    return 0


def _error_message(body: str) -> str:
    try:
        err = json.loads(body).get("error", {})
        return err.get("message", body) if isinstance(err, dict) else str(err)
    except (ValueError, AttributeError):
        return body[:300]
