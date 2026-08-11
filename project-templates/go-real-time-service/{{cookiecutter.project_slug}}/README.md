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

## Generated code: use `make`, not `go build`

Two things in this repo are generated and gitignored:

| Artifact                         | Produced by     | From                    |
| -------------------------------- | --------------- | ----------------------- |
| `**/*_templ.go`                  | `make generate` | `**/*.templ`            |
| `web/resources/static/index.css` | `make css`      | `web/resources/styles/` |

`go build ./...` on a fresh clone fails, because the functions the handlers
call (`Page`, `TodosView`, …) only exist in the generated files. That failure
is the design. If the generated code were committed instead, editing a
`.templ` file and forgetting to regenerate would leave `go build` quietly
compiling the old version, and you would debug behaviour that does not match
the source in front of you. A missing symbol is a better error than a stale
one.

So go through `make`, which regenerates first every time:

```bash
make build      # generate + css + go build -tags=prod
make test       # generate + go test
make lint       # generate + golangci-lint
make run-dev    # air, which re-runs templ generate on every rebuild
```

CI needs `make setup` (or at least `make generate`) before it compiles
anything. The Dockerfile already runs `make generate css` in its builder
stage.

If your editor reports undefined symbols right after cloning, run
`make generate` once.

## Quick start

```bash
cp .env.example .env.server
make setup      # go mod tidy, download client assets, generate, build css
make start-dev  # tmux session: server + stylesheet watcher
```

Then open <http://localhost:8080>. `make stop-dev` tears the session down.

`make setup` needs network access once, to vendor `datastar.js` and the DaisyUI
plugin into `web/resources/`. Those are ordinary files with Make rules, so they
are fetched only when missing and committed like any other dependency;
`make update-assets` re-downloads them.

## Commands

| Task                       | Command           |
| -------------------------- | ----------------- |
| First-time setup           | `make setup`      |
| Dev session (tmux)         | `make start-dev`  |
| Stop dev session           | `make stop-dev`   |
| Server only, hot reload    | `make run-dev`    |
| Stylesheet watcher only    | `make run-css-dev`|
| Build production binary    | `make build`      |
| Run production binary      | `make run`        |
| Tests                      | `make test`       |
| Lint                       | `make lint`       |
| Refresh vendored JS/CSS    | `make update-assets` |
| Deploy to Kubernetes       | `make deploy`     |

`make help` lists everything.

`make lint` needs a `golangci-lint` recent enough for this module's Go version;
older builds crash while loading packages rather than reporting a problem with
your code. Everything else runs off the pinned `tool` entries in `go.mod`.

Dev targets tee to `logs/`, so you can inspect a running server without
switching terminals:

```bash
tail -f logs/server.log
jq 'select(.level == "ERROR")' logs/server.log
```

## How the real-time part works

Three demo features, each showing a different pattern. Delete the ones you do
not need.

### `features/todos` — shared state via a KV watch

The one to copy for most work. The page renders an empty placeholder:

```html
<div id="todos" data-init="@get('/api/todos')"></div>
```

That single GET never returns. The handler subscribes to a JetStream KV key and
blocks. Mutation routes (`POST /api/todos/item/{idx}/toggle`, …) do not render
anything — they load the board, mutate it, write it back, and return `204`. The
write wakes the watcher, which renders the fragment and pushes it down the open
stream.

The upshot is that the UI reflects the *state*, not the *request*. A change
written by another tab, another user, or a background job arrives on screen by
exactly the same path as one the user clicked.

### `features/monitor` — pure server push

A ticker samples host stats and calls `MarshalAndPatchSignals`. No client
interaction at all. This is the shape for dashboards and live feeds.

### `features/counter` — one-shot signal patches

Each button opens an SSE response, patches two signals, and closes. No watcher,
no persistence. The shape for cheap interactions that do not need shared state.

## Architecture

```
cmd/server/          urfave/cli entrypoint, graceful shutdown
router/              joins the feature slices onto one http.ServeMux
internal/httpx/      adapter chain, middleware, JSON helpers
internal/broker/     embedded NATS JetStream, memory-backed KV buckets
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

Environment variables, loaded from `.env.server` by the Makefile:

| Variable         | Default    | Purpose                                  |
| ---------------- | ---------- | ---------------------------------------- |
| `SERVER_ADDR`    | `:8080`    | Listen address                           |
| `LOG_LEVEL`      | `warn`     | `debug`, `info`, `warn`, `error`         |
| `SESSION_SECRET` | `change-me`| Cookie signing key — set this in prod    |
| `NATS_PORT`      | free port  | Embedded NATS port                       |

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

`make deploy` builds the image, pushes it, and applies `k8s/prod` with the git
SHA substituted in. The Dockerfile runs the codegen steps itself, so the image
builds from a clean checkout.

The ingress sets `proxy-buffering: off` and long read/send timeouts. Without
those, SSE updates arrive in batches or the connection is reaped mid-stream —
the most common way a working real-time app breaks once it is behind a proxy.
