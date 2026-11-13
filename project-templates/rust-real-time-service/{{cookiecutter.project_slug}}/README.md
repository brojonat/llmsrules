# {{cookiecutter.project_name}}

{{cookiecutter.description}}

A real-time web service: Rust on the back end (axum, Tokio), [Datastar][ds]
on the front, [maud][maud] for HTML checked at compile time, and SQLite for
state. The browser opens one long-lived SSE connection per view and the server
pushes HTML down it. There is no client-side framework, no JSON API for the
UI, and no frontend build step.

[ds]: https://data-star.dev
[maud]: https://maud.lambda.xyz

## Quick start

```bash
mise run setup   # toolchain, crates, .env from .env.example
mise run dev     # rebuild + restart on save, logs tee'd to logs/serve.log
```

Open <http://localhost:{{cookiecutter.default_port}}>, then a second tab. The first build compiles
tokio, axum and sqlx (a minute or so); after that an edit rebuilds and
restarts in a few seconds.

## Commands

`mise tasks` lists everything.

| Task | Command |
| --- | --- |
| Dev server (hot reload) | `mise run dev` |
| Tests / lint / format | `mise run test` / `mise run lint` / `mise run fmt` |
| Load test a running server | `mise run load` (or `scripts/load.sh 500 /todos/stream`) |
| Release build, then run it | `mise run build` / `mise run serve` |
| Container image | `mise run docker-build` |
| Deploy to Kubernetes | `mise run deploy` |
| Follow production logs | `mise run logs` |

## Configuration

| Flag | Env | Default |
| --- | --- | --- |
| `--addr` | `SERVER_ADDR` | `0.0.0.0:{{cookiecutter.default_port}}` |
| `--database-url` | `DATABASE_URL` | `sqlite://data/app.db` (created if missing) |
| `--frame-tick-ms` | `FRAME_TICK_MS` | `100`: the render budget, and the fastest a view changes on screen |
| `--log-level` | `LOG_LEVEL` | `warn` (any `tracing` filter) |
| `--log-format` | `LOG_FORMAT` | `json` (`pretty` in `.env.example`) |

## How the real-time part works

Every live view is rendered by one tick loop, `src/frames.rs`, and never by a
request. A *frame* is the whole HTML of a view; Datastar morphs it in, and
per-connection Brotli ships only what changed between frames.

```
writes ──> SQLite ──> mark_dirty(key) ──> tick: render dirty keys ──> watch channel ──> SSE streams
 (204)                                    (once per key, not per tab)   (newest wins)    (send newest)
```

- **Writes mark, ticks render.** A write changes the database, marks the view
  dirty, and returns `204`. Every `FRAME_TICK_MS` the renderer renders each
  dirty view once and publishes it. A burst of writes is one render; ten tabs
  on one view are one render.
- **Only watched views render.** A view with no open stream is skipped, and
  subscribing marks it dirty, so a new viewer always gets a fresh frame.
- **Each view's frames go out on a `tokio::sync::watch` channel**, which holds
  one value. A slow client skips to the newest frame instead of queueing
  frames, and a stream unsubscribes by being dropped: when the browser goes
  away, axum drops the response body, which drops the receiver.

Three demo features. Delete the ones you don't need.

### `src/todos.rs`: a per-session view over SQLite

The one to copy for most work. The page renders an empty placeholder:

```html
<section id="todos" data-init="@get('/todos/stream', {openWhenHidden: true})"></section>
```

That GET never returns: it subscribes to `todos/<session id>` and sends frames.
The writes (`POST /todos`, `/todos/{id}/toggle`, ...) run their SQL with
`AND session = ?`, mark the view dirty, and return `204`. The UI reflects the
state, not the request: a change from another tab, or a background job that
calls `mark_dirty`, reaches the screen by the same path as a click.

The session is a random id in an `HttpOnly` cookie, set on first visit by the
`session` middleware. It is not authentication; add real auth before storing
anything that matters.

### `src/monitor.rs`: one shared view, sampled

Every viewer sees the same host stats, so there is one key, `monitor`, and
one sample + render per 500 ms however many tabs are open. Nothing writes host
stats, so the view is registered with `every` instead of being marked dirty.
It also shows how many streams are watching it. The shape for dashboards and
live feeds.

### `src/counter.rs`: one-shot signal patches

Each click opens an SSE response, patches two signals, and closes. No
renderer, no database. The shape for cheap interactions with no shared state.

### Adding a live view

1. Write a render function: `async fn(key: String) -> anyhow::Result<String>`
   that renders the whole view from current state, and register it in
   `main.rs` with `renderer.handle("myview/", render_fn(...), None)`.
2. The stream handler is two lines:
   `let frames = app.renderer.subscribe(&key)?; Ok(sse(frames, app.shutdown.clone(), &headers))`.
3. Wherever state changes: `app.renderer.mark_dirty(&key)`, after the write
   commits. When unsure which keys a write affects, mark them all; the tick
   bounds the cost.

Pick the key by what the view depends on: one key for a view everyone shares
(`monitor`), one per session or per user for personal views (`todos/<id>`).

### Backpressure

| If... | then... |
| --- | --- |
| writes outpace renders | marks coalesce in a set; N writes in one tick are one render |
| a tick takes longer than its budget | the interval skips missed ticks (`MissedTickBehavior::Skip`); frame rate falls, latency and memory don't grow |
| a client reads slower than frames arrive | the `watch` channel holds only the newest frame; the stream sends that one when the socket frees up |

None of that loses data, because every frame is the whole view.

### Compression and memory

`src/stream.rs` Brotli-compresses each stream at **quality 1**, lgwin 17. The
per-stream encoder is what a crowd multiplies, and quality sets its size far
more than the window does. Measured on this service, 300 open streams on the
monitor view:

| Encoding | Memory per open stream |
| --- | --- |
| none | 29 KiB |
| Brotli quality 1 | 41 KiB |
| Brotli quality 5 | 1,063 KiB |

The price is bandwidth on small frames: per frame, quality 1 sent 267 bytes
where quality 5 sent 91 on a 1 KB view, 1.7 KB against 1.2 KB on a 16 KB
view, and 7.3 KB against 4.6 KB on a 64 KB view. The table in `stream.rs` has the details; keep 2^lgwin
at least twice your largest frame.

### Measuring it

The tick is the benchmark. `/metrics` has `frames_tick_duration_seconds`,
`frames_tick_overruns_total`, `frames_subscribers` and
`frames_render_errors_total`. Under sustained overrun the log prints one
summary per 20 s window:

```json
{"level":"WARN","fields":{"message":"frames: tick overrun","budget":"100ms","ticks":180,"p50":"98ms","p95":"146ms","p99":"298ms","max":"453ms"}}
```

`mise run load` opens 300 streams against a running server and prints those
metrics and the server's memory. If overruns persist, lengthen
`FRAME_TICK_MS` first, then render the dirty views concurrently in
`Renderer::step` (the comment there says how).

## Layout

| File | Job |
| --- | --- |
| `src/main.rs` | Flags (clap), logging, wiring, shutdown |
| `src/app.rs` | `AppState`, router, session and metrics middleware, page layout, `AppError` |
| `src/frames.rs` | The tick loop that renders every live view |
| `src/stream.rs` | Frames to an SSE response, Brotli |
| `src/db.rs` | Opens SQLite (WAL, busy timeout) and runs migrations |
| `src/todos.rs`, `monitor.rs`, `counter.rs` | The features: routes, SQL, view, handlers |
| `static/app.css` | Plain CSS, served at `/static/app.css` |
| `migrations/` | The schema, embedded in the binary and applied at startup |

SQL is plain strings through sqlx (`query_as` onto `#[derive(FromRow)]`
structs), checked when it runs; the tests run every query. See the
`rust-datastar-minimal` template's README for the full tour, including the
move to compile-time checked `query!`.

## Deployment

The `Dockerfile` builds a static musl binary with cargo-chef and copies it
onto an empty `scratch` image (about 10 MB, unprivileged, no shell). The
binary is PID 1 and handles SIGTERM itself: it cancels a token that ends every
open stream and the tick loop, so shutdown takes milliseconds instead of
waiting on streams that never finish.

`k8s/prod` is a kustomize directory with a 1 GiB volume for the database.
**One replica, `Recreate` strategy**: SQLite has one writer, and the tick loop
and its subscribers live in one process. The ingress turns off proxy
buffering and raises the read timeout, or streams would stall or be cut.
Scaling out means moving state to Postgres and broadcasting `mark_dirty`
between replicas (Postgres `LISTEN/NOTIFY`, NATS).

`mise run deploy` builds and pushes `{{cookiecutter.docker_registry}}/{{cookiecutter.project_slug}}:<commit>`
(override with `DOCKER_REPO`), applies `k8s/prod` with that tag, and waits for
the rollout. It refuses to run with uncommitted changes. Set the ingress host
in `k8s/prod/ingress.yaml` first.
