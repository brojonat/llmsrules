# {{cookiecutter.project_name}}

{{cookiecutter.description}}

Read `README.md` first for the architecture, then `TODO.md` for what is in
flight, then `LEARNINGS.md` for what has bitten people.

| Task | Command |
| --- | --- |
| Setup | `mise run setup` |
| Data | `mise run build` (generate + build) |
| Dev server | `mise run dev` (tees `logs/serve.log`) |
| Tests | `mise run test` |
| Lint | `mise run lint` / `mise run fmt` |
| Load test | `mise run loadtest:smoke` |
| Kill orphan | `mise run stop` |

`mise tasks` lists the rest.

Rules of the road:

- The server owns state. Pages render from it; commands mutate it and answer
  204; the read stream repaints. Never render from a command.
- Signals are for UI-only state (a panel open, a toggle). Anything the server
  also knows does not belong in a signal; chart data travels as element
  attributes in the morph.
- The warehouse is read-only to the server and rebuilt by `build`. Anything
  users create goes in the app DB (`appdb.py`), via an appended migration.
- A tool call is just another command source: the assistant changes the
  dashboard through the same `update_filter` the page uses.
- Numbers the assistant states must come from tools. When you change what a
  tool returns or the prompt says, run the evals (`mise run eval`, costs
  money) and compare pass rates over a few `--repeat`s.
- Tests build their own small warehouse with the real generator; never point
  a test at `data/`.
- Don't touch `README.md`, `TODO.md`, `CHANGELOG.md` or `LEARNINGS.md` during
  normal work. Update them in one pass when the session winds down.
