# {{cookiecutter.project_name}}

{{cookiecutter.description}}

Read `README.md` first for the architecture, then `TODO.md` for what is in
flight, then `LEARNINGS.md` for what has bitten people.

| Task           | Command          |
| -------------- | ---------------- |
| Setup          | `make setup`     |
| Dev server     | `make run-serve` |
| Tests          | `make test`      |
| Lint           | `make lint`      |
| Kill orphan    | `make stop`      |

Rules of the road:

- The server owns state. Pages render from the store; writes mutate the
  store and answer 204; the read stream repaints. Do not render from a write.
- Signals are for UI-only state and for carrying input up. Anything the
  server also knows does not belong in a signal.
- Tests use temp dirs and their own embedded NATS. Never point a test at a
  real data dir.
- Update `CHANGELOG.md`, `TODO.md`, and `LEARNINGS.md` after every task.
