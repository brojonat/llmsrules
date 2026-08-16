#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "datastar-py>=1.0.2",
#     "jinja2>=3.1",
#     "starlette>=0.47",
#     "uvicorn>=0.35",
# ]
# ///
"""{{cookiecutter.project_name}} -- a complete real-time web app in one file.

It follows the Tao of Datastar: the backend owns all state, one long-lived SSE
request streams the UI down, and short-lived POSTs send commands up. That split
is CQRS, and it is what makes the app multiplayer for free -- every connected
browser renders from the same server-side state, so a write from any of them
shows up in all of them.

Dependencies are declared inline (PEP 723), so `./main.py` bootstraps its own
environment on first run and there is nothing to install by hand. The browser
gets datastar.js from a CDN via one script tag; there is no frontend build step.

    ./main.py    # or: uv run main.py
                 # then open http://localhost:8000 in two tabs
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator, Iterator

import jinja2
import uvicorn
from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.starlette import DatastarResponse, datastar_response, read_signals
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

# ---------------------------------------------------------------------------
# State. The backend is the source of truth; the browser holds none of this.
# ---------------------------------------------------------------------------


class Store:
    """The whole application state, plus a way to wait on changes.

    No lock: asyncio runs one coroutine at a time and nothing here awaits
    mid-mutation, so every method below is already atomic.
    """

    def __init__(self) -> None:
        self._messages: list[str] = []
        self._watchers: set[asyncio.Event] = set()

    def list(self) -> list[str]:
        return list(self._messages)

    def add(self, message: str) -> None:
        self._messages.append(message)
        self._notify()

    def clear(self) -> None:
        self._messages.clear()
        self._notify()

    @contextlib.contextmanager
    def watch(self) -> Iterator[asyncio.Event]:
        """Register a listener for the duration of a `with` block."""
        changed = asyncio.Event()
        self._watchers.add(changed)
        try:
            yield changed
        finally:
            self._watchers.discard(changed)

    def _notify(self) -> None:
        for changed in self._watchers:
            # Already-set events coalesce. Watchers re-read current state when
            # they wake, so that is not a lost update.
            changed.set()


# ---------------------------------------------------------------------------
# Templates. One source of truth for markup, rendered entirely on the server.
# "board" is both part of the first page load and the fragment pushed on every
# change -- Datastar morphs it in, so there is no separate client-side view.
# ---------------------------------------------------------------------------

{% raw %}PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.2/bundles/datastar.js"></script>
<style>
  body { font-family: system-ui, sans-serif; max-width: 40rem; margin: 2rem auto; padding: 0 1rem; }
  form { display: flex; gap: .5rem; margin: 1rem 0; }
  input { flex: 1; padding: .5rem; }
  /* 16px minimum, or iOS Safari zooms the page when the input is focused. */
  input, button { font-size: 1rem; }
  li { padding: .25rem 0; }
  footer { margin-top: 1rem; color: #666; font-size: .875rem; }
</style>
</head>
<!-- The one long-lived read request. It never returns; the server pushes
     every subsequent render down it. openWhenHidden keeps the stream alive
     when the tab is backgrounded -- without it Datastar closes GET streams on
     hide and reconnects on show, so a backgrounded tab goes stale. -->
<body data-init="@get('/updates', {openWhenHidden: true})">
{% include "board.html" %}
</body>
</html>
"""

# The live region. Every write re-renders this whole element and morphs it in:
# no per-field patching, no diffing by hand.
BOARD = """<main id="board">
<h1>Messages</h1>
<!-- A command, not a render request. The server answers 204 and the update
     arrives on the SSE stream above. -->
<form data-on:submit__prevent="@post('/add'); $message = ''">
  <input name="message" placeholder="Say something" autocomplete="off" aria-label="Message" data-bind:message>
  <button type="submit">Send</button>
</form>
<ul aria-live="polite">
{% for message in messages %}<li>{{ message }}</li>
{% else %}<li><em>No messages yet.</em></li>
{% endfor %}</ul>
<footer>
{{ messages|length }} message(s) &middot; open a second tab to watch them sync
<button data-on:click="@post('/clear')">Clear</button>
</footer>
</main>
"""{% endraw %}

templates = jinja2.Environment(
    loader=jinja2.DictLoader({"page.html": PAGE, "board.html": BOARD}),
    autoescape=True,
)


def render_board(store: Store) -> str:
    return templates.get_template("board.html").render(messages=store.list()).strip()


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def index(request: Request) -> HTMLResponse:
    store: Store = request.app.state.store
    html = templates.get_template("page.html").render(
        title=request.app.state.title, messages=store.list()
    )
    return HTMLResponse(html)


@datastar_response
async def updates(request: Request) -> AsyncIterator[str]:
    """The read side: render current state, then block until something changes,
    forever. It never renders in response to a request.

    Starlette cancels this generator when the client goes away, which unwinds
    the `with` block and unregisters the watcher.
    """
    store: Store = request.app.state.store
    with store.watch() as changed:
        while True:
            yield SSE.patch_elements(render_board(store))
            await changed.wait()
            changed.clear()


async def add(request: Request) -> DatastarResponse:
    """The write side: mutate and return nothing. The open stream is what puts
    the result on screen."""
    store: Store = request.app.state.store
    signals = await read_signals(request) or {}
    message = str(signals.get("message", "")).strip()
    if message:
        store.add(message)
    return DatastarResponse()  # 204, empty body


async def clear(request: Request) -> DatastarResponse:
    request.app.state.store.clear()
    return DatastarResponse()


app = Starlette(
    routes=[
        Route("/", index),
        Route("/updates", updates),
        Route("/add", add, methods=["POST"]),
        Route("/clear", clear, methods=["POST"]),
    ]
)
app.state.store = Store()
app.state.title = "{{cookiecutter.project_name}}"


if __name__ == "__main__":
    # No timeout_keep_alive tuning and no response timeout: anything that cuts
    # an idle connection would sever the SSE stream mid-flight.
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
