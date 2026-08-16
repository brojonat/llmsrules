# {{cookiecutter.project_name}}

{{cookiecutter.description}}

A real-time, multiplayer web app in one file.

```bash
go run .
```

Open <http://localhost:8080> in two tabs and type in one of them.

## What it is

`main.go` is the whole program: state, templates, and four routes. There is no
build step, no codegen, no `node_modules`, and no vendored assets — the browser
gets `datastar.js` from a CDN in a single script tag.

One dependency: the official [Datastar Go SDK][sdk]. It owns the SSE wire
format, flushing, and signal decoding, so none of that appears in this file.

| Route          | Method | Job                                                  |
| -------------- | ------ | ---------------------------------------------------- |
| `/`            | GET    | First paint, and opens the stream                    |
| `/updates`     | GET    | The long-lived read. Pushes HTML on every change      |
| `/add`         | POST   | A command. Mutates and returns `204`                  |
| `/clear`       | POST   | A command. Mutates and returns `204`                  |

## The shape it is showing off

This follows [the Tao of Datastar][tao]. Four ideas do all the work.

**The backend is the source of truth.** All state is a `[]string` and a mutex
in `store`. The browser holds one signal, `message`, bound to the text input —
that is it. Nothing is duplicated client-side, so nothing can drift.

**CQRS: one long-lived read, many short-lived writes.** `GET /updates` never
returns. It renders the board, blocks on a change, renders again, forever.
`POST /add` mutates and answers `204` with an empty body — it does not render.
The update reaches the screen on the stream, not in the POST response.

That split is why the app is multiplayer without any extra code. A write from
one browser wakes every watcher, so all connected clients re-render from the
same state. Nothing in `handleAdd` knows how many people are looking.

**Patch elements, and trust morph.** The server re-renders the entire `<main
id="board">` on every change and sends the whole thing. Datastar morphs it in,
touching only what actually differs. There is no per-field patching and no
diffing by hand — and morph is careful enough that another user's message
arriving does not clobber the text you are halfway through typing.

**Backend templating.** `html/template` renders both the first page load and
every subsequent fragment from the same `board` template, so the markup exists
in exactly one place.

[tao]: https://data-star.dev/guide/the_tao_of_datastar

## The SDK surface

Three calls carry the whole app:

```go
sse := datastar.NewSSE(w, r)        // upgrade to a stream; flushes every event
sse.PatchElements(html)             // send HTML for the browser to morph in
datastar.ReadSignals(r, &signals)   // decode the browser's signals
```

`NewSSE` writes the SSE headers (including `X-Accel-Buffering: no`, so nginx
does not buffer the stream) and flushes each event as it is sent. Pass
`datastar.WithCompression()` to negotiate Brotli/gzip on the stream —
repetitive HTML compresses at ratios around 200:1, and it is the single biggest
win available here.

`ReadSignals` reads a JSON body on writes and the `?datastar=` query parameter
on reads. **Call it before `NewSSE`** — upgrading the response first closes the
request body out from under it, and the SDK's error message will tell you so.

The SDK also does signal patching (`PatchSignals`), script execution, redirects,
and `templ` integration (`PatchElementTempl`). See the [docs][sdk].

[sdk]: https://github.com/starfederation/datastar-go

## Gotchas

- **`data-init="@get('/updates', {openWhenHidden: true})"`.** Without that
  option Datastar closes GET streams when the tab is hidden and reconnects when
  it is shown again, so a backgrounded tab goes stale. Keeping it open is what
  you almost always want for a live view.
- **Never wait for `networkidle`.** The SSE stream is a request that never
  completes, so the network is never idle. In Playwright use
  `wait_until="domcontentloaded"`; in anything else, wait for an element.
- **Do not add a `WriteTimeout`** to the server — it severs SSE streams
  mid-flight. Same goes for ingress and load balancer idle timeouts.
- **`html/template` strips HTML comments** from its output, so the comments in
  the `board` template never reach the wire.

## Making it yours

Replace the `store` with whatever your app is actually about, and rewrite the
`board` template. Keep the shape: writes mutate and return nothing, the stream
re-renders, and state stays on the server.

Things deliberately left out, in rough order of when you will want them:
graceful shutdown, `/healthz`, structured logging, per-session state instead of
one global board, and persistence. State here is in memory and disappears on
restart.

If you find yourself adding several of those, the `go-real-time-service`
template is the same architecture with templ, an embedded NATS broker for
per-session state, Prometheus metrics, and a Kubernetes deployment.
`python-datastar-minimal` is this same file in Python.

## Notes for agents

- `go run .` is the whole dev loop. There is no Makefile and no codegen.
- `go.mod` and `go.sum` are committed, so `go run .` works on a fresh clone
  without a `go mod tidy` step.
- `main.go` is meant to stay one file. If it needs splitting up, that is the
  signal to move to `go-real-time-service` instead of growing this.
- Mutation handlers must not render. If you are writing HTML in a `POST`
  handler, you have left the pattern.
- The datastar.js URL is pinned to a release tag. Bump it deliberately, and
  keep it in step with the SDK version in `go.mod`.
