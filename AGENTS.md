# Development Philosophy

This document captures high-level preferences that apply across every project
bootstrapped from this repo. Language- and framework-specific patterns live in
the individual skills under `skills/` — this file is about the values that
should shape decisions before any code gets written.

## Unix Philosophy

- **Do one thing well.** Each component has a single, well-defined responsibility.
- **Write programs that compose.** Design for piping and standard interfaces.
  Outputs should be valid inputs for other programs.
- **Be quiet by default.** No news is good news. Only output when there's
  something unexpected to report.
- **Text streams are the universal interface.** JSON on stdout, human-readable
  status and errors on stderr, exit codes for success/failure.

## Stdout vs stderr

- **stdout is for machine-readable output.** Default to JSON. Pipe it, parse it,
  compose it.
- **stderr is for humans.** Progress messages, warnings, errors, and anything
  else that shouldn't contaminate a pipeline.
- **Interactive CLIs may use friendly formatting on stdout,** but always offer a
  `--json` / `--format=json` flag for scripting.

## Favor Simplicity

Complex solutions need complex problems to justify them. Reach for the simple
tool first:

- **SQLite over a dedicated database server** when a single process is enough.
- **Standard library HTTP over frameworks** — handlers as functions, middleware
  as composition.
- **Plain HTML (with a sprinkle of HTMX or similar) over heavy frontend stacks**
  when the task doesn't demand a SPA.
- **Environment variables over elaborate config DSLs.**
- **Standard SQL over ORM magic.**
- **Plain JSON over custom binary protocols.**

## Simple CLIs

- One command, one job. Compose with pipes, not flags.
- Subcommands only when you genuinely have a family of related operations.
- Sensible defaults; require no flags for the common case.
- `-h` / `--help` always works. Help text shows real usage, not marketing.
- Exit 0 on success, non-zero on failure. No "successfully completed" banners.

## Hot Reloading

Development should feel instant. Every project should have a hot-reload story:
Air for Go, `uvicorn --reload` for Python, equivalent tooling for whatever
stack. Edit file, see result. If hot reload isn't working, fix it before
writing more code.

## Makefiles as the Front Door

Every project needs a `Makefile` with the primary targets (`build`, `test`,
`lint`, `run-*`, `deploy-*`) so that humans and agents share a single entry
point. No one should have to dig through READMEs to figure out the right
command — `make help` lists everything.

**Dev targets must tee stdout and stderr to files in `logs/`.** A coding agent
can't iterate on a bug it can't see. When `make run-server` dumps output into
a separate terminal, the agent is blind; when it tees to `logs/server.log`,
the agent can `tail` / `grep` / `jq` the output, diagnose what's broken, fix
the code, and watch the reload pick it up.

```makefile
.PHONY: run-server
run-server: ## Run server with hot reload, tee to logs/
	@mkdir -p logs
	$(call setup_env, .env.server)
	uv run uvicorn server.main:app --reload 2>&1 | tee logs/server.log
	# Go equivalent:
	# air 2>&1 | tee logs/server.log
```

Keep `logs/` gitignored. The value is the feedback loop, not the artifacts.

## Language Idioms

Honor the culture of the language you're in.

### The Zen of Python

> Beautiful is better than ugly. Explicit is better than implicit. Simple is
> better than complex. Flat is better than nested. Readability counts. There
> should be one — and preferably only one — obvious way to do it.

Use dataclasses and type hints. Prefer composition over inheritance. Let
exceptions propagate to the right layer. Don't fight the GIL; use async or
processes when it matters.

### Go Idioms

Accept interfaces, return structs. Pass `context.Context` as the first
parameter. Handle every error with `fmt.Errorf("...: %w", err)`. Goroutines
have owners that know when they stop. The stdlib is the framework — reach for
it first, and only adopt a dependency when the stdlib genuinely falls short.

## Explicit Dependencies

Never hide dependencies in global state, singletons, or package-level
variables. Constructors take what they need as parameters. This applies in
every language:

- Dependencies are visible in type signatures.
- Testing becomes trivial — swap real for fake at construction time.
- Lifecycle is clear — whoever constructs something owns its cleanup.

## Production-Ready Defaults

Every service should ship with:

- Structured logging (JSON in prod, pretty in dev), level controlled by
  `LOG_LEVEL`.
- A `/healthz` endpoint.
- Prometheus metrics on `/metrics`.
- Graceful shutdown on SIGTERM.
- Secrets from environment variables. Never commit `.env` files.

## Error Handling

- Handle errors at the layer that can do something about them. Don't swallow,
  don't blindly re-raise.
- Wrap errors with context as they propagate. The final message should tell a
  story: what was being attempted, what went wrong, and why.
- Validate at system boundaries (user input, external APIs). Trust internal
  code.

## When In Doubt

Ask: *"Does this add essential value, or does it just add complexity?"* If you
can't articulate the essential value in one sentence, it's probably
complexity.
