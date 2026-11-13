# {{cookiecutter.project_name}}

{{cookiecutter.description}}

Read `README.md` first, then `TODO.md` for what is in flight, then
`LEARNINGS.md` for what has bitten people.

| Task | Command |
| --- | --- |
| Dev server | `mise run dev` (tees `logs/serve.log`) |
| Tests | `mise run test` |
| Lint | `mise run lint` / `mise run fmt` |
| A token for curl | `mise run token --sub you \| jq -r .token` |

## Skills

`install-skills.sh` installs the `rust` skill. Before writing async code, read
its references (in `.agents/skills/rust/references/` or wherever your agent
installed it); they are short:

- `async.md` for any `.await`, `spawn`, or blocking call in a handler.
- `cancellation.md` for anything with `select!`, `timeout`, `try_join`, a
  mutex, or a handler that must finish its work even if the client goes away
  (an HTTP handler is dropped when the client disconnects).
- `signals.md` before touching shutdown, SIGTERM, or the container entrypoint
  (this binary is PID 1 in its image).
- `cli.md` before adding flags or subcommands.

## Rules of the road

- Handlers get dependencies from `State<AppState>` or extractors, never from
  globals. Tests build the router with `app(state)` and call it in-process.
- A new resource is a new module shaped like `src/items.rs` (its SQL and its
  handlers), with its routes merged in `app::app`.
- Schema changes are new files in `migrations/`; never edit one that shipped.
- SQL is plain strings checked at runtime, so every query needs a test that
  runs it (in-memory SQLite, `db::test_pool()`).
- `Claims` in a handler's arguments is what makes a route require a token.
  Extractors that read the body (`Json`) go last.
- Handlers return `Result<_, AppError>`. Add a variant to `AppError` rather
  than building error responses by hand; server errors are logged there.
- Label metrics by route template (`MatchedPath`), never the raw path.
- `anyhow` with `.context(...)` in `main`; `thiserror` types everywhere else.
- `mise run lint` treats clippy warnings as errors; keep it clean.
- Don't touch `README.md`, `TODO.md`, `CHANGELOG.md` or `LEARNINGS.md` during
  normal work. Update them in one pass when the session winds down.
