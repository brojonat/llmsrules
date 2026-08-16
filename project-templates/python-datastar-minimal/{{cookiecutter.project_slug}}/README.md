# {{cookiecutter.project_name}}

{{cookiecutter.description}}

A real-time, multiplayer web app in one file.

```bash
./main.py
```

Open <http://localhost:8000> in two tabs and type in one of them.

## What it is

`main.py` is the whole program: state, templates, four routes, and a PEP 723
dependency block that `uv` resolves on first run. There is no `pyproject.toml`,
no lockfile, no virtualenv to create, no `node_modules`, and no vendored assets
— the browser gets `datastar.js` from a CDN in a single script tag.

| Route      | Method | Job                                              |
| ---------- | ------ | ------------------------------------------------ |
| `/`        | GET    | First paint, and opens the stream                |
| `/updates` | GET    | The long-lived read. Pushes HTML on every change |
| `/add`     | POST   | A command. Mutates and returns `204`             |
| `/clear`   | POST   | A command. Mutates and returns `204`             |

Four dependencies: [`datastar-py`][sdk] for the SSE protocol, Starlette for
routing, uvicorn to serve it, and Jinja2 for the markup.

## The shape it is showing off

This follows [the Tao of Datastar][tao]. Four ideas do all the work.

**The backend is the source of truth.** All state is a `list[str]` on the
server. The browser holds one signal, `message`, bound to the text input — that
is it. Nothing is duplicated client-side, so nothing can drift.

**CQRS: one long-lived read, many short-lived writes.** `GET /updates` never
returns. It renders the board, blocks on a change, renders again, forever.
`POST /add` mutates and answers `204` with an empty body — it does not render.
The update reaches the screen on the stream, not in the POST response.

That split is why the app is multiplayer without any extra code. A write from
one browser wakes every watcher, so all connected clients re-render from the
same state. Nothing in `add()` knows how many people are looking.

**Patch elements, and trust morph.** The server re-renders the entire `<main
id="board">` on every change and sends the whole thing. Datastar morphs it in,
touching only what actually differs. There is no per-field patching and no
diffing by hand — and morph is careful enough that another user's message
arriving does not clobber the text you are halfway through typing.

**Backend templating.** Jinja2 renders both the first page load and every
subsequent fragment from the same `board.html` template, so the markup exists in
exactly one place.

[tao]: https://data-star.dev/guide/the_tao_of_datastar

## The protocol

`datastar-py` gives you two functions and a response class, and that is nearly
the whole surface used here:

```python
SSE.patch_elements(html)      # -> an SSE event the browser morphs into the DOM
await read_signals(request)   # -> the browser's signals, as a dict
DatastarResponse(events)      # -> a streaming response; 204 when empty
```

`@datastar_response` on an async generator turns each yielded event into a
frame on the stream. On the wire, a patch looks like this:

```
event: datastar-patch-elements
data: elements <main id="board">
data: elements <h1>Messages</h1>
data: elements </main>

```

The SDK also does signal patching, script execution, and redirects. See the
[docs][sdk] when you need them.

[sdk]: https://github.com/starfederation/datastar-python

## Gotchas

- **`read_signals()` returns `None` unless the request carries a
  `Datastar-Request` header.** `datastar.js` always sends it; `curl` does not.
  Add `-H 'Datastar-Request: true' -H 'Content-Type: application/json'` when
  testing writes by hand, or you will silently get no signals.
- **Never wait for `networkidle`.** The SSE stream is a request that never
  completes, so the network is never idle. In Playwright use
  `wait_until="domcontentloaded"`; in anything else, wait for an element.
- **Do not add a response or idle timeout to the server.** Anything that reaps
  a long-open connection severs the stream mid-flight.

## Making it yours

Replace `Store` with whatever your app is actually about, and rewrite the
`BOARD` template. Keep the shape: writes mutate and return nothing, the stream
re-renders, and state stays on the server.

Things deliberately left out, in rough order of when you will want them:
graceful shutdown, `/healthz`, structured logging, per-session state instead of
one global board, and persistence. State here is in memory and disappears on
restart.

`Store` has no lock because asyncio runs one coroutine at a time and nothing in
it awaits mid-mutation. The moment you add an `await` inside a mutation — a
database call, say — that reasoning stops holding, and you need either a real
transaction or an `asyncio.Lock`.

If you find yourself adding several of those, `python-service` is the same
stack with FastAPI, structlog, metrics, and a Kubernetes deployment;
`go-real-time-service` is this architecture in Go with templ and an embedded
NATS broker for per-session state.

## Notes for agents

- `./main.py` is the whole dev loop. There is no Makefile and no codegen.
  Restart it to pick up changes; `uv` caches the environment so it is instant.
- `main.py` is meant to stay one file. If it needs splitting up, that is the
  signal to move to `python-service` instead of growing this.
- Mutation handlers must not render. If you are writing HTML in a `POST`
  handler, you have left the pattern.
- The datastar.js URL is pinned to a release tag. Bump it deliberately, and
  keep it in step with the `datastar-py` version in the PEP 723 block.
