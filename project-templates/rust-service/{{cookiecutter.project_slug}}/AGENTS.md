# {{cookiecutter.project_name}}

{{cookiecutter.description}}

Read `README.md` first, then `TODO.md` for what is in flight, then
`LEARNINGS.md` for what has bitten people.

| Task | Command |
| --- | --- |
| Dev server | `mise run dev` (tees `logs/serve.log`) |
| Tests | `mise run test` |
| Lint | `mise run lint` / `mise run fmt` |

Rules of the road:

- Handlers get dependencies from `State<AppState>` or extractors, never from
  globals. Tests build the router with `app(state)` and call it in-process.
- Label metrics by route template (`MatchedPath`), never the raw path.
- Errors bubble up with context (`map_err(|e| format!("doing X: {e}"))` or
  `anyhow::Context` once it's a dependency); `main` reports them and exits 1.
- `mise run lint` treats clippy warnings as errors; keep it clean.
- Don't touch `README.md`, `TODO.md`, `CHANGELOG.md` or `LEARNINGS.md` during
  normal work. Update them in one pass when the session winds down.
