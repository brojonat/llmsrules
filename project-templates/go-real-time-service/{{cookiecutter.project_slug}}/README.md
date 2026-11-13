# {{cookiecutter.project_name}}

{{cookiecutter.description}}

A real-time web service: Go on the back end, [Datastar][ds] on the front,
[templ][templ] for typed HTML, and an embedded [NATS][nats] JetStream broker as
the state layer. The browser opens one long-lived SSE connection and the server
pushes HTML fragments and signal updates down it. There is no client-side
framework, no JSON API for the UI, and no build step involving npm.

[ds]: https://data-star.dev
[templ]: https://templ.guide
[nats]: https://docs.nats.io

## Generated code: use `mise`, not `go build`

Two things in this repo are generated and gitignored:

| Artifact                         | Produced by         | From                    |
| -------------------------------- | ------------------- | ----------------------- |
| `**/*_templ.go`                  | `mise run generate` | `**/*.templ`            |
| `web/resources/static/index.css` | `mise run css`      | `web/resources/styles/` |

`go build ./...` on a fresh clone fails, because the functions the handlers
call (`Page`, `TodosView`, …) only exist in the generated files. That failure
is the design. If the generated code were committed instead, editing a
`.templ` file and forgetting to regenerate would leave `go build` quietly
compiling the old version, and you would debug behaviour that does not match
the source in front of you. A missing symbol is a better error than a stale
one.

So go through `mise`, which regenerates first every time:

```bash
mise run build  # generate + css + go build -tags=prod
mise run test   # generate + go test -race
mise run lint   # generate + golangci-lint
mise run dev    # air (re-runs templ generate on every rebuild) + css watcher
```

CI needs `mise run setup` (or at least `mise run generate`) before it compiles
anything. The Dockerfile runs the same codegen steps in its builder stage.

If your editor reports undefined symbols right after cloning, run
`mise run generate` once.

## Quick start

```bash
cp .env.example .env
mise install      # Go and golangci-lint, pinned in mise.toml
mise run setup    # go mod download, fetch client assets, generate, build css
mise run dev      # server + stylesheet watcher; Ctrl-C stops both
```

Then open <http://localhost:8080>. `mise run start-dev` runs the same two
processes in a detached tmux session instead; `mise run stop-dev` tears it down.

`mise run setup` needs network access once, to vendor `datastar.js` and the
DaisyUI plugin into `web/resources/`. `scripts/vendor.sh` fetches only the files
that are missing, and they are committed like any other dependency;
`mise run update-assets` re-downloads them.

## Commands

| Task                       | Command                  |
| -------------------------- | ------------------------ |
| First-time setup           | `mise run setup`         |
| Dev (server + css watcher) | `mise run dev`           |
| Dev session in tmux        | `mise run start-dev`     |
| Stop tmux session          | `mise run stop-dev`      |
| Server only, hot reload    | `mise run dev:server`    |
| Stylesheet watcher only    | `mise run dev:css`       |
| Build production binary    | `mise run build`         |
| Run production binary      | `mise run run`           |
| Tests                      | `mise run test`          |
| Lint                       | `mise run lint`          |
| Refresh vendored JS/CSS    | `mise run update-assets` |
| Deploy to Kubernetes       | `mise run deploy`        |

`mise tasks` lists everything.

`mise.toml` pins Go and `golangci-lint` so the linter always matches the
module's Go version; an older `golangci-lint` crashes while loading packages
rather than reporting a problem with your code. templ, air and gotailwind run
off the pinned `tool` entries in `go.mod`.

Dev tasks tee to `logs/`, so you can inspect a running server without
switching terminals:

```bash
tail -f logs/server.log
jq 'select(.level == "ERROR")' logs/server.log
```

## How the real-time part works

Every live view is rendered by one tick loop, `internal/frames`, and never by a
request. This is immediate-mode rendering on the server: a *frame* is the
whole HTML of a view, Datastar morphs it in, and per-connection Brotli ships
only what changed between frames.

```
writes ──> state ──> MarkDirty(key) ──> tick: render dirty keys ──> frame slots ──> SSE streams
 (204)    (NATS KV)                     (once per key, not per tab)  (latest wins)   (send newest)
```

- **Writes mark, ticks render.** Mutations save state and return `204`; the
  save marks the view dirty. Every `FRAME_TICK` (default 100ms) the renderer
  renders each dirty view once and hands the bytes to every stream watching
  it. A burst of writes is one render; ten tabs on one view are one render.
- **Only watched views render.** A view with no open stream is skipped, and
  subscribing marks it dirty, so a new viewer always gets a fresh frame and
  nothing outlives its viewers.
- **Overload sheds frames, not the server.** See *Backpressure* below.

Three demo features. Delete the ones you do not need.

### `features/todos` — per-session view over a KV bucket

The one to copy for most work. The page renders an empty placeholder:

```html
<div id="todos" data-init="@get('/api/todos', {openWhenHidden: true})"></div>
```

That GET never returns: it subscribes to the view `todos/<session id>` and
sends frames. Mutation routes (`POST /api/todos/item/{idx}/toggle`, …) load
the board, mutate it, write it back to the KV bucket, and return `204`. One
watcher on the whole bucket marks the written session's view dirty, and the
next tick pushes the new frame down every stream on that session.

The upshot is that the UI reflects the *state*, not the *request*. A change
written by another tab, another user, or a background job lands on screen by
exactly the same path as one the user clicked.

### `features/monitor` — one shared view, sampled

Every viewer sees the same host, so there is one view key, `monitor`, and one
sample + render per interval no matter how many tabs are open. Nothing writes
host stats, so the view is registered with `frames.Every(500ms)` instead of
being marked dirty. This is the shape for dashboards and live feeds.

### `features/counter` — one-shot signal patches

Each button opens an SSE response, patches two signals, and closes. No
renderer, no persistence. The shape for cheap interactions that do not need
shared state.

### Adding a live view

1. Write a `frames.RenderFunc`: `func(ctx, key string) ([]byte, error)` that
   renders the whole view from current state.
2. `renderer.Handle("myview/", render)` in your feature's `SetupRoutes`.
3. In the stream handler: `sub, err := renderer.Subscribe(key)`, then
   `sub.Stream(ctx, func(b []byte) error { return sse.PatchElements(string(b)) })`.
4. Wherever state changes: `renderer.MarkDirty(key)`. When unsure which keys a
   write affects, mark them all; the tick bounds the cost.

Pick the key by what the view depends on: one key for a view everyone shares
(`monitor`), one per session for personal views (`todos/<id>`).

### Backpressure

Work can pile up in three places, and each one is bounded:

| If…                               | then…                                                                         |
| --------------------------------- | ----------------------------------------------------------------------------- |
| writes outpace renders            | marks coalesce in a set; N writes in one tick are one render                  |
| a tick takes longer than its budget | `time.Ticker` drops the missed ticks; frame rate falls, latency and memory do not grow |
| a client reads slower than frames arrive | its slot is overwritten; when the socket frees up it sends the newest frame |

None of that loses data, because every frame is the whole view: skipping one
loses nothing the next one does not carry.

### Measuring it

The tick is the benchmark. `/metrics` exposes `frames_tick_duration_seconds`,
`frames_tick_overruns_total`, `frames_subscribers`, and
`frames_render_errors_total`. Under sustained overrun the log prints one
summary per 20s window:

```json
{"level":"WARN","msg":"frames: tick overrun","budget":"100ms","ticks":180,"p50":"100ms","p95":"146ms","p99":"298ms","max":"453ms"}
```

To load test, open a few hundred streams with `curl -N` and watch that line.
If overruns persist, first lengthen `FRAME_TICK`, then split the render loop
in `frames.step` across a few goroutines.

## Architecture

```
cmd/server/          urfave/cli entrypoint, graceful shutdown
router/              joins the feature slices onto one http.ServeMux
internal/httpx/      adapter chain, middleware, JSON helpers
internal/broker/     embedded NATS JetStream, memory-backed KV buckets
internal/frames/     the tick loop that renders every live view
features/<name>/     one vertical slice: routes, handlers, model, view, templ
features/common/     shared layout and components
web/resources/       static assets; disk in dev, embedded + hashed in prod
```

A feature owns everything it needs and exposes `SetupRoutes`. Adding one is a
directory plus a line in `router/router.go`.

Routing is `net/http`'s `ServeMux` — no third-party router. Handlers are
functions returning `http.Handler` with their dependencies as parameters.

### Templates stay declarative

Computation belongs in Go, not in `.templ` files. `features/todos/view.go`
builds a `View` struct — counts, filtered rows, mode tabs, the input's initial
signal payload — and `view.templ` only interpolates it. That keeps the markup
readable and puts the interesting logic somewhere you can unit test, which is
what `model_test.go` does.

## State and scaling

NATS runs **in process**. JetStream's store directory is a temp dir wiped on
exit and every bucket is memory-backed with a TTL, so the service is stateless:
no volumes, no PVC, no migrations. Restarting loses the demo boards, which for
a template is the honest default.

Consequently the Kubernetes manifest runs `replicas: 1`. Two pods would each
hold their own state and users would see whichever they were routed to. When
this service grows real state, put it in whatever data system it is wired into,
or move to an external NATS cluster and point `internal/broker` at it — that is
a deliberate decision, not something to stumble into by bumping `replicas`.

## Configuration

Environment variables, loaded from `.env` by mise:

| Variable         | Default    | Purpose                                  |
| ---------------- | ---------- | ---------------------------------------- |
| `SERVER_ADDR`    | `:8080`    | Listen address                           |
| `LOG_LEVEL`      | `warn`     | `debug`, `info`, `warn`, `error`         |
| `SESSION_SECRET` | `change-me`| Cookie signing key — set this in prod    |
| `NATS_PORT`      | free port  | Embedded NATS port                       |
| `FRAME_TICK`     | `100ms`    | Render tick for live views               |

## Endpoints

| Path        | Purpose                                     |
| ----------- | ------------------------------------------- |
| `/`         | Todos demo                                  |
| `/counter`  | Counter demo                                |
| `/monitor`  | System monitor demo                         |
| `/healthz`  | Health check                                |
| `/metrics`  | Prometheus metrics                          |
| `/static/*` | Client assets                               |
| `/reload`   | Live-reload stream (dev builds only)        |

## Deployment

`mise run deploy` builds the image, pushes it, and applies `k8s/prod` with the
git SHA substituted in (`scripts/deploy.sh`, which reads `DOCKER_REGISTRY` from
`.env.prod`). The Dockerfile runs the codegen steps itself, so the image
builds from a clean checkout.

The ingress sets `proxy-buffering: off` and long read/send timeouts. Without
those, SSE updates arrive in batches or the connection is reaped mid-stream —
the most common way a working real-time app breaks once it is behind a proxy.
