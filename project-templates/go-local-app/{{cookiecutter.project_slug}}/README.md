# {{cookiecutter.project_name}}

{{cookiecutter.description}}

A local app: one Go binary a user installs with `go install`, runs on their
own machine, and opens in a browser. It owns its state, needs no external
services, and has no frontend build step.

```
go install {{cookiecutter.go_mod}}/cmd/{{cookiecutter.project_slug}}@latest
{{cookiecutter.project_slug}} serve          # http://127.0.0.1:{{cookiecutter.default_port}}
```

## What is in the box

- **CLI** with `urfave/cli` v3. `serve` is the only subcommand; add siblings
  in `cmd/{{cookiecutter.project_slug}}/`.
- **Embedded NATS JetStream** (`internal/bus`), in-process only, no TCP port.
  One file-backed KV bucket under `--data-dir` (default `~/.{{cookiecutter.project_slug}}`)
  holds app state and is the wake-up bus for every open page.
- **Datastar over SSE** (`internal/web`), following the Tao of Datastar: the
  server owns all state, each page holds one long-lived read stream that
  re-renders its live region whenever the bucket changes, and writes are
  short requests that mutate and answer 204. Templates are `html/template`
  files embedded in the binary; the same template renders the first paint
  and every patch.
- **A demo feature** to delete: items with a title, a star, and a click-to-edit
  note; a starred-only filter persisted as a preference; and a header search
  that patches a results slot. Together they exercise every pattern.
- **File watching** (`internal/watch`): `--watch DIR` fingerprints a directory
  every `--poll` and bumps the bucket when anything changes, so pages built
  from local files stay current.
- **Diagnostics** at `/admin`: sampled process metrics in a JetStream stream,
  stat tiles with sparklines, meters against limits, admin-set thresholds
  with breach status, and a limits table. `/metrics` in Prometheus text
  format with no client library. `/healthz` answers `ok`.
- **Production defaults**: slog with `LOG_LEVEL` and `LOG_FORMAT=json`,
  graceful shutdown on SIGINT/SIGTERM, Brotli on streams, `{{cookiecutter.env_prefix}}_ADDR` and
  `{{cookiecutter.env_prefix}}_DATA_DIR` env overrides.
- **Air hot reload** via `make run-serve`, output teed to `logs/serve.log`.

## Layout

```
cmd/{{cookiecutter.project_slug}}/   main.go (CLI), serve.go (wiring: bus, store, sampler, http)
internal/bus/        embedded NATS + JetStream, KV buckets, streams
internal/state/      the app's KV-backed store (items, preferences, fs stamp)
internal/watch/      directory fingerprinting and the poll loop
internal/metrics/    collector, sampler, history, thresholds, limits, /metrics
internal/web/        handlers, the stream helper, templates/
```

## Adding a page

1. Add `templates/<name>.html` defining `{{ '{{' }}define "region"{{ '}}' }}` with a single root
   element that has an `id`.
2. Add a view function returning the region's data, embedding `pageData`.
3. Register `GET /<path>` with `s.page(name, view)` and `GET /<path>/stream`
   with `s.stream(name, view, s.stateWatch)`.
4. Writes: a handler that mutates the store and returns 204. The stream
   repaints every open tab.

## Development

```
make setup         # go mod tidy, install air
make run-serve     # hot reload
make test          # fixtures in temp dirs only
make lint
make stop          # kill an orphaned server on the port
```

Tests never touch a real data dir; each test starts its own embedded NATS in
a temp dir.
