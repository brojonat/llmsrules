---
name: air-go
description:
  Hot-reload Go apps with cosmtrek/air during development. Use when setting up
  dev workflows for Go HTTP servers, configuring .air.toml, or debugging
  hot-reload issues with SQLite, port binding, or file watchers.
---

# Air — Go Hot Reload

[Air](https://github.com/air-verse/air) watches Go source files and
rebuilds/restarts your app on changes. Essential for web server development
where you want sub-second feedback.

## Install

```bash
go install github.com/air-verse/air@latest
```

## Basic usage

Run `air` in your project root. With no config, it watches `.go` files,
rebuilds, and restarts. For anything non-trivial, use a `.air.toml`.

## .air.toml

```toml
root = "."
tmp_dir = "tmp"

[build]
  bin = "./tmp/main"
  cmd = "go build -o ./tmp/main ."
  delay = 500
  exclude_dir = ["tmp", "k8s", "cmd", "node_modules", "vendor"]
  exclude_regex = ["_test\\.go$"]
  include_ext = ["go", "html", "css", "js", "yml", "yaml", "toml"]
  kill_delay = "1s"
  send_interrupt = true
  stop_on_error = true

[misc]
  clean_on_exit = true
```

### Key settings explained

| Setting          | What it does                                                           | Why it matters                                                                   |
| ---------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `delay`          | Milliseconds to wait after a file change before rebuilding             | Prevents rapid-fire rebuilds when saving multiple files                          |
| `kill_delay`     | Time to wait after killing the old process before starting the new one | Critical for SQLite/file locks — the old process needs time to release resources |
| `send_interrupt` | Send SIGINT before SIGKILL                                             | Allows graceful shutdown (flush writes, close DB connections)                    |
| `stop_on_error`  | Don't restart on build errors                                          | Prevents crash loops when you have a syntax error                                |
| `include_ext`    | File extensions to watch                                               | Add `html`, `css`, `js` to reload on frontend changes too                        |
| `exclude_dir`    | Directories to ignore                                                  | Exclude test fixtures, k8s manifests, vendored deps                              |
| `exclude_regex`  | File patterns to ignore                                                | Skip test files to avoid rebuilding when only tests change                       |
| `clean_on_exit`  | Remove tmp dir on exit                                                 | Prevents stale binaries from confusing the next run                              |

## Makefile integration

```makefile
.PHONY: dev dev-email dev-clean

# Dev: console output, fresh state
dev: dev-clean
	air

# Dev: real emails, LAN-accessible for mobile testing
dev-email: dev-clean
	$(call setup_env, .env.prod)
	SMTP_HOST=smtp.example.com \
	BASE_URL=http://$(LAN_IP):8080 \
	air

dev-clean:
	@rm -f app.db app.db-shm app.db-wal tmp/main
	@-lsof -ti :8080 | xargs kill -9 2>/dev/null || true
```

The `dev-clean` target is important — it kills anything on the port and removes
stale DB files before starting fresh.

## Passing environment variables

Air inherits the parent shell's environment. Set env vars inline before `air`:

```bash
# Inline
PORT=3000 DEBUG=true air

# From .env file in Makefile
$(call setup_env, .env.dev)
air
```

Do NOT put env vars in `.air.toml` — it doesn't support that. Environment is
always from the shell.

## Common issues and fixes

### "address already in use"

The previous process didn't die. Fix:

```bash
lsof -ti :8080 | xargs kill -9
```

Or add to `dev-clean` target as shown above.

### "database is locked" (SQLite)

Air kills the old process and starts the new one, but SQLite WAL files can
linger. Fix with these `.air.toml` settings:

```toml
[build]
  kill_delay = "1s"          # Give old process time to release the lock
  send_interrupt = true      # Graceful shutdown via SIGINT
  pre_cmd = ["rm -f app.db-shm app.db-wal"]  # Clean stale lock files
```

If using an in-memory DB or ephemeral dev DB, just delete it on each rebuild:

```toml
[build]
  pre_cmd = ["rm -f app.db app.db-shm app.db-wal"]
```

### "too many open files" on large projects

Air's file watcher can hit OS limits. Exclude unnecessary directories:

```toml
[build]
  exclude_dir = ["tmp", "vendor", "node_modules", ".git", "k8s", "docs"]
```

### Air exits immediately in background/CI

Air is a foreground tool — it watches stdin for `Ctrl+C`. In scripts or CI, use
`go run .` instead. Air is for interactive development only.

### Changes not detected

Check that your file extension is in `include_ext` and the directory isn't in
`exclude_dir`. Air only watches extensions you explicitly list.

## Watching non-Go files

To rebuild on HTML/CSS/JS changes (useful for apps that serve static files):

```toml
[build]
  include_ext = ["go", "html", "css", "js"]
```

Air will rebuild the Go binary even when only frontend files change. This is
fine — Go builds are fast and the restart picks up the new static files.

## Multi-binary projects

If your project has multiple binaries (`cmd/server`, `cmd/worker`), point `cmd`
at the one you want:

```toml
[build]
  cmd = "go build -o ./tmp/server ./cmd/server"
  bin = "./tmp/server"
```

Run a second air instance in another terminal for the worker if needed, with a
separate config:

```bash
air -c .air.worker.toml
```
