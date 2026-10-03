"""A stand-in OpenAI-compatible LLM for load tests.

Streams canned text at a fixed token rate, reports usage the way OpenRouter
does, and costs nothing. Point the server at it with
LLM_BASE_URL=http://127.0.0.1:8399/v1 to load-test chat streaming with
hundreds of concurrent conversations.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

WORDS = (
    "Resolution time is the mean over resolved tickets, from opened to resolved. Open tickets count toward "
    "volume but not toward resolution time, and satisfaction is the mean over the tickets whose customer answered. "
).split()


def create_app(tokens: int = 200, tokens_per_second: float = 60, first_token_delay: float = 0.4) -> Starlette:
    async def completions(request: Request) -> StreamingResponse:
        body = await request.json()
        prompt_chars = sum(len(json.dumps(m.get("content", ""))) for m in body.get("messages", []))

        async def stream() -> AsyncIterator[bytes]:
            yield b": FAKE PROCESSING\n\n"
            await asyncio.sleep(first_token_delay)
            started = time.monotonic()
            for i in range(tokens):
                word = WORDS[i % len(WORDS)] + " "
                chunk = {"choices": [{"index": 0, "delta": {"role": "assistant", "content": word}}]}
                yield f"data: {json.dumps(chunk)}\n\n".encode()
                # Pace against the clock, not per-sleep, so the rate holds under load.
                await asyncio.sleep(max(0.0, started + (i + 1) / tokens_per_second - time.monotonic()))
            usage = {"prompt_tokens": prompt_chars // 4, "completion_tokens": tokens, "cost": 0.0}
            yield f"data: {json.dumps({'choices': [], 'usage': usage})}\n\ndata: [DONE]\n\n".encode()

        return StreamingResponse(stream(), media_type="text/event-stream")

    async def models(request: Request) -> JSONResponse:
        return JSONResponse({"data": [{"id": "fake", "context_length": 200_000}]})

    return Starlette(routes=[Route("/v1/chat/completions", completions, methods=["POST"]), Route("/v1/models", models)])
