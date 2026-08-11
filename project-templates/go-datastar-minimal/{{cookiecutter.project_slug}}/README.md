# {{cookiecutter.project_name}}

{{cookiecutter.description}}

A real-time, multiplayer web app in one file, no dependencies.

```bash
go run .
```

Open <http://localhost:8080> in two tabs and type in one of them.

## What it is

`main.go` is the whole program: state, templates, the Datastar SSE protocol,
and four routes. There is no build step, no `go mod tidy`, no `node_modules`,
and no vendored assets — the browser gets `datastar.js` from a CDN in a single
script tag.

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

## The protocol, in full

Datastar's wire format is why no SDK is needed here. To patch the DOM, send an
SSE event named `datastar-patch-elements` with one `data: elements ` line per
line of HTML:

```
event: datastar-patch-elements
data: elements <main id="board">
data: elements <h1>Messages</h1>
data: elements </main>

```

That is `patchElements`, and it is nine lines. Reading the browser's signals is
`readSignals`: a JSON body on writes, a `?datastar=` query parameter on reads.

The official [Go SDK][sdk] is worth adopting once you want signal patching,
script execution, redirects, or compression. Until then this is the entire
surface.

[sdk]: https://github.com/starfederation/datastar-go

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

## Notes for agents

- `go run .` is the whole dev loop. There is no Makefile and no codegen.
- `main.go` is meant to stay one file. If it needs splitting up, that is the
  signal to move to `go-real-time-service` instead of growing this.
- Do not add a `WriteTimeout` to the server — it severs SSE streams mid-flight.
- Mutation handlers must not render. If you are writing HTML in a `POST`
  handler, you have left the pattern.
- The datastar.js URL is pinned to a release tag. Bump it deliberately.
