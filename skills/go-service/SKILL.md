---
name: go-service
description: Build Go microservices with stdlib HTTP handlers, sqlc, urfave/cli, and slog. Use when creating or modifying a Go HTTP server, adding routes, middleware, database queries, or CLI commands.
---

# Go Service

Production-grade Go microservices using the standard library, sqlc for SQL, urfave/cli for commands, and slog for structured logging.

## Core Principles

- **Do one thing well**: Single responsibility per component
- **Simple over complex**: Plain JSON, standard SQL, environment variables
- **Compose**: Design for piping and standard interfaces
- **Explicit dependencies**: No globals, no singletons, pass everything as parameters

## Project Structure

```
.
├── cmd/
│   ├── server/          # Backend service entry point
│   └── client/          # CLI entry point
├── cli/                 # CLI implementation
├── client/              # Public client library
├── internal/            # Internal packages
│   └── db/             # Generated code (from sqlc)
├── migrations/          # SQL schema migrations
├── queries/             # SQL queries for sqlc
├── examples/            # Usage examples
├── testdata/            # Test fixtures
├── Makefile
├── .air.toml           # Air configuration
├── sqlc.yaml           # sqlc configuration
├── go.mod
├── README.md
└── CHANGELOG.md
```

## Handler Functions Pattern

Write functions that return `http.Handler` (following Mat Ryer's approach):

```go
func handleListWallets(store TransactionStore, logger *slog.Logger) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        ctx := r.Context()

        wallets, err := store.ListWallets(ctx)
        if err != nil {
            logger.ErrorContext(ctx, "failed to list wallets", "error", err)
            http.Error(w, "internal error", http.StatusInternalServerError)
            return
        }

        w.Header().Set("Content-Type", "application/json")
        json.NewEncoder(w).Encode(wallets)
    })
}
```

## Middleware Composition

```go
type adapter func(http.Handler) http.Handler

// adaptHandler applies adapters in reverse order so the first is outermost
func adaptHandler(h http.Handler, adapters ...adapter) http.Handler {
    for i := len(adapters) - 1; i >= 0; i-- {
        h = adapters[i](h)
    }
    return h
}

// Usage:
mux.Handle("GET /wallets", adaptHandler(
    handleListWallets(store, logger),
    withRequestID(),
    withLogging(logger),
    withMetrics(promRegistry),
    withJWTAuth(jwtSecret),
))
```

## Dependency Injection

```go
// Bad: hidden dependency on global
var db *sql.DB
func SaveTransaction(txn *Transaction) error {
    _, err := db.Exec("INSERT INTO transactions ...")
    return err
}

// Good: explicit dependencies
type TransactionStore interface {
    Save(ctx context.Context, txn *Transaction) error
}

type PostgresStore struct {
    db *sql.DB
}

func NewPostgresStore(db *sql.DB) *PostgresStore {
    return &PostgresStore{db: db}
}

// Dependencies are clear at construction time
store := NewPostgresStore(db)
poller := NewWalletPoller(solanaClient, store, natsConn)
```

## Structured Logging with slog

```go
func setupLogger(level slog.Level) *slog.Logger {
    opts := &slog.HandlerOptions{Level: level}
    return slog.New(slog.NewJSONHandler(os.Stderr, opts))
}

// Most logs at DEBUG level
logger.DebugContext(ctx, "polling wallet", "wallet", walletAddress, "last_slot", lastSlot)

// INFO for lifecycle events only
logger.InfoContext(ctx, "server started", "addr", addr, "version", version)

// ERROR for failures
logger.ErrorContext(ctx, "failed to store transaction", "error", err, "signature", sig)
```

Control verbosity via `LOG_LEVEL` env var. Default to WARN in production, DEBUG in development.

## SQL with sqlc

Write SQL, get type-safe Go:

```yaml
# sqlc.yaml
version: "2"
sql:
  - engine: "postgresql"
    queries: "queries/"
    schema: "migrations/"
    gen:
      go:
        package: "db"
        out: "internal/db"
```

Always regenerate after schema changes and commit the generated code.

## Error Handling

```go
// Always handle errors
txns, err := client.GetTransactions(ctx)
if err != nil {
    return fmt.Errorf("failed to get transactions: %w", err)
}
```

## CLI with urfave/cli

Clean, composable command-line interfaces with automatic env var binding and built-in help.

## Development Workflow

1. **Plan**: Design the interface first
2. **Test first (TDD)**: Write the test, write minimal code, refactor
3. **Server + Client**: Every server feature gets a client method and CLI subcommand
4. **Makefile**: `make test`, `make lint`, `make dev`, `make build-server`
5. **Hot reload**: Use [Air](https://github.com/cosmtrek/air) for development
6. **Linting**: `golangci-lint` with strict settings, fix all warnings

## Unix Philosophy

- **Be quiet by default**: Only output on errors or significant events
- **JSON on stdout**: Machine-readable output, `--format=table|json|csv` for humans
- **Errors to stderr**: Keep stdout clean for piping
- **Exit codes**: 0 = success, non-zero = error
