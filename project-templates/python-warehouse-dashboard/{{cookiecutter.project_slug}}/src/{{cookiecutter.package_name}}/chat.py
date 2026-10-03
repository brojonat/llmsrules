"""Per-session conversations with the dashboard assistant.

State lives on the server. A session's conversation is a list of messages
plus, while a reply is streaming, the partial assistant text. Sending is a
command: it appends the user's message, starts a background task that streams
the reply from the LLM into `pending`, and returns. Each update wakes the
session's page streams, which re-render the chat region, so tokens reach the
browser as fat morphs on the stream the page already holds.

The assistant can also drive the dashboard through tools. A reply is a loop:
stream a turn; if the model called tools, run them (a tool call is just
another source of the same commands the page's controls send, so the view
updates over the same stream), append the results, and stream the next turn.

Nothing here is persisted: conversations live in memory and end with "new
conversation" or a restart. Feedback, which is kept, goes to the app DB.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from .llm import Delta, LLMConfig, LLMError, Reasoning, ToolCall, ToolCalls, Usage, stream_chat

log = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 4000
MAX_TOOL_ROUNDS = 6  # model turns per reply that may call tools (queries get retried), before we stop it
NOTIFY_EVERY = 0.05  # seconds: batch token deltas into ~20 renders/s at most
CHECKIN_AFTER = 3  # ask "how is the assistant doing?" after this many answers, once per conversation


class Tools(Protocol):
    """What the assistant can do to a session's dashboard. Implemented by
    tools.ViewTools, which shares the dashboard's state with the web layer."""

    def specs(self) -> list[dict]: ...

    async def call(self, sid: str, name: str, args: dict) -> dict: ...


def _add_usage(a: Usage | None, b: Usage) -> Usage:
    if a is None:
        return b
    cost = None if a.cost is None and b.cost is None else (a.cost or 0.0) + (b.cost or 0.0)
    return Usage(a.prompt_tokens + b.prompt_tokens, a.completion_tokens + b.completion_tokens, cost,
                 a.cached_tokens + b.cached_tokens)  # fmt: skip


def estimate_tokens(text: str) -> int:
    """A provider-agnostic estimate (~4 characters per token). Only used until
    the provider reports exact counts for this conversation."""
    return len(text) // 4 + 4


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool"
    content: str
    interrupted: bool = False  # assistant reply cut short by an error
    tool_calls: list[ToolCall] = field(default_factory=list)  # assistant asked for these
    tool_call_id: str = ""  # tool: which call this answers
    name: str = ""  # tool: which tool ran
    arguments: str = ""  # tool: what it was called with (for the chat's action chips)
    attachment: dict | None = None  # tool: rendered in the chat (a chart), never sent to the model
    ok: bool = True  # tool: did it succeed
    reasoning: list[dict] | None = None  # assistant: thinking blocks, sent back as-is, never shown

    def to_api(self) -> dict:
        if self.role == "tool":
            return {"role": "tool", "tool_call_id": self.tool_call_id, "content": self.content}
        msg: dict = {"role": self.role, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [c.to_api() for c in self.tool_calls]
        if self.reasoning:
            msg["reasoning_details"] = self.reasoning
        return msg

    def tokens(self) -> int:
        return estimate_tokens(self.content + "".join(c.name + c.arguments for c in self.tool_calls))


@dataclass
class Conversation:
    messages: list[Message] = field(default_factory=list)
    pending: str | None = None  # assistant text streaming in; None when idle
    error: str | None = None
    # Exact token count reported by the provider for the last model turn
    # (system + messages[:exact_upto]), or None before the first reply.
    exact_tokens: int | None = None
    exact_upto: int = 0
    task: asyncio.Task | None = field(default=None, repr=False)
    # The feedback check-in, Claude Code style: None (not asked yet), "asking"
    # (1 Bad · 2 Fine · 3 Good · Dismiss), "rated" (optional follow-up text),
    # "done", "dismissed" or "closed". `checkin_id` is the stored rating's row.
    checkin: str | None = None
    checkin_id: int | None = None
    cost: float = 0.0  # USD across every model turn, when the provider reports it

    @property
    def streaming(self) -> bool:
        return self.task is not None and not self.task.done()

    @property
    def answers(self) -> int:
        """Replies the user actually got (assistant text, not tool calls)."""
        return sum(1 for m in self.messages if m.role == "assistant" and m.content and not m.tool_calls)

    def transcript(self) -> list[dict]:
        """The conversation as stored with feedback: what was said and which
        tools ran, with long tool results cut."""
        out = []
        for m in self.messages:
            item: dict = {"role": m.role, "content": m.content if m.role != "tool" else m.content[:2000]}
            if m.tool_calls:
                item["tool_calls"] = [{"name": c.name, "arguments": c.arguments} for c in m.tool_calls]
            if m.role == "tool":
                item["name"] = m.name
            out.append(item)
        return out


@dataclass
class ContextUsage:
    tokens: int
    window: int  # 0 = unknown
    exact: bool

    @property
    def pct(self) -> float:
        return 100 * self.tokens / self.window if self.window else 0.0


class Chats:
    """All sessions' conversations and the LLM calls behind them."""

    def __init__(
        self,
        cfg: LLMConfig,
        http: httpx.AsyncClient,
        system_prompt: Callable[[], str],
        notify: Callable[[str], None],
        tools: Tools | None = None,
        on_reply: Callable[[float, Usage | None, bool], None] = lambda *_: None,
        on_in_flight: Callable[[int], None] = lambda _: None,
        tokens_today: Callable[[], int] = lambda: 0,
    ) -> None:
        self.cfg = cfg
        self.http = http
        self.system_prompt = system_prompt
        self.notify = notify
        self.tools = tools
        self.on_reply = on_reply  # (seconds, usage, ok) for metrics and the usage table
        self.on_in_flight = on_in_flight  # replies streaming right now, for metrics
        self.tokens_today = tokens_today  # all users, against cfg.daily_tokens
        self.window = cfg.context_window
        self.in_flight = 0
        self._slots = asyncio.Semaphore(cfg.max_concurrent)
        self._conversations: dict[str, Conversation] = {}

    def get(self, sid: str) -> Conversation:
        return self._conversations.get(sid) or Conversation()

    def conversation(self, sid: str) -> Conversation:
        """The session's conversation, created if needed (for UI state like the check-in)."""
        return self._conversations.setdefault(sid, Conversation())

    def usage(self, sid: str) -> ContextUsage:
        """Tokens the next request would send (system prompt and tool schemas included)."""
        conv = self.get(sid)
        if conv.exact_tokens is not None:
            tokens, rest, exact = conv.exact_tokens, conv.messages[conv.exact_upto :], True
        else:
            tools = json.dumps(self.tools.specs()) if self.tools else ""
            tokens, rest, exact = estimate_tokens(self.system_prompt() + tools), conv.messages, False
        tokens += sum(m.tokens() for m in rest)
        if conv.pending:
            tokens += estimate_tokens(conv.pending)
        return ContextUsage(tokens, self.window, exact and not rest and not conv.pending)

    def send(self, sid: str, text: str) -> str | None:
        """Start a reply. Returns an error message instead when it can't."""
        text = text.strip()
        if not self.cfg.configured:
            return "chat is not configured on this server"
        if not text:
            return "empty message"
        conv = self.conversation(sid)
        if error := self._check(sid, conv, text):
            # Also shown in the panel: a command's response body goes nowhere.
            conv.error = error
            self.notify(sid)
            return error
        conv.messages.append(Message("user", text))
        if conv.checkin in ("done", "rated"):
            conv.checkin = "closed"  # the conversation moved on; drop the thanks / unanswered note box
        conv.error = None
        conv.pending = ""
        conv.task = asyncio.create_task(self._reply(sid, conv))
        self.notify(sid)
        return None

    def _check(self, sid: str, conv: Conversation, text: str) -> str | None:
        if conv.streaming:
            return "wait for the current reply to finish"
        if self.cfg.daily_tokens and self.tokens_today() >= self.cfg.daily_tokens:
            return "the assistant has used today's budget; it resets at 00:00 UTC"
        if len(text) > MAX_MESSAGE_CHARS:
            return f"messages are limited to {MAX_MESSAGE_CHARS:,} characters"
        room = self.window - self.cfg.max_tokens
        if self.window and self.usage(sid).tokens + estimate_tokens(text) > room:
            return "this conversation is out of context; start a new one"
        return None

    def clear(self, sid: str) -> None:
        conv = self._conversations.pop(sid, None)
        if conv and conv.task and not conv.task.done():
            conv.task.cancel()
        self.notify(sid)

    async def _reply(self, sid: str, conv: Conversation) -> None:
        started = time.perf_counter()
        total: Usage | None = None  # every model turn of this reply, tool rounds included
        ok = False
        try:
            async with self._slots:
                self.in_flight += 1
                self.on_in_flight(self.in_flight)
                try:
                    for turn in range(MAX_TOOL_ROUNDS + 1):
                        calls, usage, reasoning = await self._turn(sid, conv, allow_tools=turn < MAX_TOOL_ROUNDS)
                        conv.messages.append(
                            Message("assistant", conv.pending or "", tool_calls=calls, reasoning=reasoning)
                        )
                        if usage:
                            total = _add_usage(total, usage)
                            conv.cost += usage.cost or 0.0
                            conv.exact_tokens = usage.prompt_tokens + usage.completion_tokens
                            conv.exact_upto = len(conv.messages)
                        conv.pending = None
                        if not calls:
                            if conv.checkin is None and conv.answers >= CHECKIN_AFTER:
                                conv.checkin = "asking"
                            break
                        await self._run_tools(sid, conv, calls)
                        conv.pending = ""
                finally:
                    self.in_flight -= 1
                    self.on_in_flight(self.in_flight)
            ok = True
        except asyncio.CancelledError:
            raise
        except (LLMError, httpx.HTTPError, ValueError) as e:
            log.warning("chat reply failed: %s", e)
            conv.error = str(e) or type(e).__name__
            if conv.pending:
                conv.messages.append(Message("assistant", conv.pending, interrupted=True))
        finally:
            conv.pending = None
            self.on_reply(time.perf_counter() - started, total, ok)
            self.notify(sid)

    async def _turn(
        self, sid: str, conv: Conversation, allow_tools: bool
    ) -> tuple[list[ToolCall], Usage | None, list[dict] | None]:
        """Stream one model turn into `pending`; return the tools it called."""
        payload = [{"role": "system", "content": self.system_prompt()}, *(m.to_api() for m in conv.messages)]
        tools = self.tools.specs() if self.tools and allow_tools else None
        calls: list[ToolCall] = []
        usage: Usage | None = None
        reasoning: list[dict] | None = None
        last_notify = 0.0
        async for event in stream_chat(self.http, self.cfg, payload, tools):
            if isinstance(event, Delta):
                conv.pending = (conv.pending or "") + event.text
                if time.perf_counter() - last_notify > NOTIFY_EVERY:
                    last_notify = time.perf_counter()
                    self.notify(sid)
            elif isinstance(event, Reasoning):
                reasoning = event.details
            elif isinstance(event, ToolCalls):
                calls = event.calls
            elif isinstance(event, Usage):
                usage = event
        return calls, usage, reasoning

    async def _run_tools(self, sid: str, conv: Conversation, calls: list[ToolCall]) -> None:
        for call in calls:
            try:
                args = json.loads(call.arguments or "{}")
                result = await self.tools.call(sid, call.name, args) if self.tools else {"error": "no tools"}
            except (ValueError, TypeError) as e:
                result = {"error": f"bad arguments: {e}"}
            attachment = result.pop("__attachment__", None)
            conv.messages.append(Message(
                "tool", json.dumps(result, default=str), tool_call_id=call.id, name=call.name, arguments=call.arguments,
                ok="error" not in result, attachment=attachment,
            ))  # fmt: skip
            self.notify(sid)
