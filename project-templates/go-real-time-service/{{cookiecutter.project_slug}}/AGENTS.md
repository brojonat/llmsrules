# {{cookiecutter.project_name}}

{{cookiecutter.description}}

Read `README.md` first for the architecture. This file is the operational
detail and the list of things that have bitten people.

## Quick Reference

| Task              | Command               |
| ----------------- | --------------------- |
| First-time setup  | `mise run setup`      |
| Dev (server+css)  | `mise run dev`        |
| Dev session, tmux | `mise run start-dev`  |
| Server only       | `mise run dev:server` |
| Tests             | `mise run test`       |
| Lint              | `mise run lint`       |
| Build             | `mise run build`      |
| Regenerate code   | `mise run generate`   |
| Deploy            | `mise run deploy`     |

`mise tasks` lists everything.

## Never run a bare `go build` or `go test`

`**/*_templ.go` and `web/resources/static/index.css` are generated and
gitignored. A fresh clone does not compile until `mise run generate` has run.

Use `mise run build` / `test` / `lint` / `dev`; each depends on `generate`. If
you see `undefined: Page` or `undefined: TodosView`, you skipped codegen — run
`mise run generate`.

That failure is deliberate. Committing the generated code would trade a missing
symbol for a stale one: a forgotten regenerate would leave `go build` compiling
the previous version of a template you just edited.

`dev:server` runs air, whose build command is
`go tool templ generate && go build`, so editing a `.templ` file is enough —
there is no separate templ watcher to remember, and `tmp/main` is never stale.

## Logs

Dev tasks tee to `logs/`:

```bash
tail -f logs/server.log
jq 'select(.level == "ERROR")' logs/server.log
```

Set `LOG_LEVEL=debug` in `.env` to see per-request lines.

## Conventions

- Handlers are functions returning `http.Handler` with dependencies as
  parameters. No globals, no singletons, no package-level state.
- Middleware composes through `httpx.Adapt(handler, adapters...)`; the first
  adapter listed is the outermost.
- Structured JSON logging via `slog` to stderr.
- A feature owns `routes.go`, `handlers.go`, its model, its view, and its
  `.templ` files. It exposes `SetupRoutes`. Register it in `router/router.go`.
- Computation goes in Go, not in templates. Build a view struct (see
  `features/todos/view.go`) and let the `.templ` file interpolate it.

## Gotchas

These are all things that fail in ways that do not point at the cause.

**Wrapping the ResponseWriter breaks SSE.** Datastar upgrades a response with
`http.NewResponseController`, which walks `Unwrap()` looking for a flushable
writer and *panics* if it cannot find one. Any middleware that wraps
`http.ResponseWriter` must implement `Unwrap() http.ResponseWriter` and
`Flush()`. `httpx.responseWriter` does; copy it if you add another wrapper.

**Write cookies and headers before opening the stream.** Once
`datastar.NewSSE` runs, headers are flushed. `svc.Board` is called before the
upgrade in `handleStream` for exactly this reason — it may set the session
cookie. Same in `handleIncrementUser`, which saves the session first.

**ServeMux panics on ambiguous patterns.** `PUT /api/todos/mode/{mode}` and
`PUT /api/todos/{idx}/edit` both match `/api/todos/mode/edit`, with neither more
specific, so registering both crashes at startup. That is why per-todo routes
carry an `/item/` segment. Keep wildcards from overlapping literals at the same
depth when adding routes.

**No `WriteTimeout` on the server.** It would sever SSE streams mid-flight.
`ReadHeaderTimeout` is set instead; leave it that way.

**Mutation handlers return no body.** They mutate and save; the save marks the
view dirty and the next render tick pushes it down the open stream. If you find yourself rendering a fragment in a
mutation handler, you have left the pattern.

**Stream handlers never render.** They `Subscribe` to a view key and call
`sub.Stream`. Rendering belongs in a `frames.RenderFunc`, which runs on the
tick. Rendering inside a stream handler brings back one render per tab per
write, which is exactly what the renderer exists to prevent.

**Do not queue frames.** A stream keeps one frame slot; newer frames overwrite
it. A buffered channel of frames per connection lets one slow client grow
memory and replay stale views.

**Writes that bypass the bucket must call `MarkDirty`.** The todos bucket
watcher marks views for anything written to NATS. State that lives elsewhere
needs an explicit `renderer.MarkDirty(key)` after the write, or the view only
updates when someone else touches it.

**Composite literals in this repo are written one element per line.** Collapsed
literals produce `{`+`{`, which cookiecutter parses as a Jinja expression when
this project is regenerated from its template.

## Adding a feature

1. `features/<name>/` with `routes.go`, `handlers.go`, and a `.templ` file.
2. Export `SetupRoutes(mux *http.ServeMux, ...) error`.
3. Join it in `router/router.go` inside the `errors.Join` call.
4. Add a `components.Page` constant and a nav entry in
   `features/common/components/nav.templ`.

## Changelog

When merging features, update `CHANGELOG.md`:

1. Add an entry under `[Unreleased]` in the right category.
2. Use imperative mood: "Add feature", not "Added feature".
3. Reference issue numbers where they exist.

Categories: Added, Changed, Deprecated, Removed, Fixed, Security.
