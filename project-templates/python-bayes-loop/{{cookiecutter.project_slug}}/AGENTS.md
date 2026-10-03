# {{cookiecutter.project_name}}

{{cookiecutter.description}}

Read `README.md` first for the architecture, then `TODO.md` for what is in
flight, then `LEARNINGS.md` for what has bitten people.

**Resuming?** `mise run loop:cpu` (no-op if it's running), then `mise run inbox`:
the user's feedback from the dashboard is your next task. Post what you do with
`mise run note`; commit a model only when an `approve` message (or the user)
says so.

**Given a dataset and a problem to model?** Use the `new-model` skill
(`.agents/skills/new-model/SKILL.md`). It covers `prepare.sql`, rewriting
`src/{{cookiecutter.package_name}}/model.py`, and passing `mise run check-model`. Install the
PyMC skills it leans on with `mise run skills`.

| Task | Command |
| --- | --- |
| Setup | `mise run setup` (CPU) or `setup:gpu`, then `mise run skills` |
| Everything, GPU | `mise run up` (db + feed + sample + dev; tees `logs/*.log`) |
| Everything, CPU | `mise run up:cpu` (small problem, own db file) |
| Everything, in tmux | `mise run loop:cpu` / `loop` (`up [NAME...]`, `status`, `restart NAME`, `down`); `up db dev` right after setup so the user can watch |
| Dashboard only | `mise run dev` (hot reload, replaces a stale server on the port) |
| SQL on the belt | `mise run query "select ..."` |
| Model contract | `mise run check-model` (after every edit to `model.py`) |
| Talk to the user | `mise run note "..."` (dashboard thread), `mise run inbox [--wait 540]` (their messages), `mise run describe -` (the model's description) |
| Figures | `mise run figures --save /tmp/figs` (read them), `mise run figure plot.png --title "..."` (add yours) |
| Data prep | `mise run prepare` (runs `prepare.sql`) |
| Tests | `mise run test` (CPU) |
| Lint | `mise run lint` / `mise run fmt` |
| Benchmarks | `mise run bench`; a file: `{{cookiecutter.project_slug}} bench --from FILE --n N --params` |
| Stop strays | `mise run stop` (this checkout's processes only) |
| Fresh belt | `mise run reset` / `mise run reset:cpu` (stop the belt first) |

`mise tasks` lists the rest.

Rules of the road:

- Everything model-specific lives in `model.py`. Feed, sample, bench and the
  dashboard use only the names its docstring lists; keep it that way.
- After editing `model.py`: `mise run check-model`, then
  `mise run loop:cpu restart sample`. Read `logs/*.log` instead of attaching.
- Every belt read goes through `belt.read()` (server-side `query()`); every
  write through `belt.write()` (bulk Arrow). Writers generate their IDs and
  write the marker row (`batches`, `fits`) last.
- The compiled program is keyed by `(n, coords)`. Anything that changes a
  shape belongs in that key; anything else is a traced argument (`pm.Data`).
- Only `sample` and `bench` import JAX. Keep JAX imports out of `belt`,
  `feed`, `model`, `web`, `describe`, `labels`, and out of module scope in `cli`.
- One naming function (`labels.scalars`) for every scalar the dashboard
  joins on. Every PyMC variable gets `dims`, Deterministics included.
- Schema changes: edit `belt.SCHEMA` / `model.OBS_DDL`; `db` refuses an old
  file and tells you to reset.
- The web server never blocks on the belt or the LLM: it starts, shows what
  it can, and catches up.
