# {{cookiecutter.project_name}}

{{cookiecutter.description}}

Read `README.md` first ("How the real-time part works" is the important
part), then `TODO.md`, then `LEARNINGS.md`.

| Task | Command |
| --- | --- |
| Dev server | `mise run dev` (tees `logs/serve.log`) |
| Tests | `mise run test` |
| Lint | `mise run lint` / `mise run fmt` |
| Load test | `mise run load` against a running server |

## Skills

`install-skills.sh` installs the `rust` and `datastar` skills. Read before
writing code (they're in `.agents/skills/`):

- datastar `SKILL.md`: the Tao, CQRS, immediate-mode rendering, and the
  Gotchas section (compression, `openWhenHidden`, timeouts).
- rust `references/cancellation.md`: an HTTP handler is dropped when its
  client disconnects. That is why writes here run in `tokio::spawn`.
- rust `references/async.md` and `references/signals.md` before touching the
  tick loop, blocking calls, or shutdown.

## Rules of the road

- Writes never render. A mutation handler changes the database, calls
  `mark_dirty` after the commit, and returns `204`. If you're writing HTML in
  a `POST` handler, you have left the pattern.
- Views never read the request. A render function gets its key and reads
  current state; everything a view depends on goes in the key.
- Every frame is the whole view. Don't send partial patches from the tick.
- Render functions must be quick and must not hold a std `Mutex` across an
  `.await`. The tick renders views one after another.
- Every query a session runs is scoped with `AND session = ?` (or the user id,
  once there is auth).
- Schema changes are new files in `migrations/`; never edit one that shipped.
- SQL is checked at runtime, so every query needs a test that runs it.
- `mise run lint` treats clippy warnings as errors; keep it clean.
- Don't touch `README.md`, `TODO.md`, `CHANGELOG.md` or `LEARNINGS.md` during
  normal work. Update them in one pass when the session winds down.
