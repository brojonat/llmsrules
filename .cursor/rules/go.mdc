# Go Development Guidelines

## Development Philosophy

This is production-grade Go code. Quality, reliability, and maintainability are paramount.

### Core Principles

**Do One Thing Extremely Well**
- Each component has a single, well-defined responsibility
- Resist feature creep and unrelated additions
- Write separate tools for separate concerns

**Simple Is Better Than Complex**
- Prefer plain JSON over custom binary protocols
- Use simple NATS pub/sub over complex routing
- Use standard SQL queries over ORM magic
- Use environment variables over elaborate config DSLs
- Complex solutions need complex problems to justify them

**Write Programs That Compose**
- Design components to work together through standard interfaces
- Enable piping and composition with other tools
- Outputs should be valid inputs for other programs

## Feature Development Workflow

### 1. Plan Before Coding
- Understand the requirement and acceptance criteria
- Design the interface first: What's the API surface?
- Consider dependencies: What components interact? What can be mocked?
- Identify edge cases: What can go wrong? How to handle errors?
- Document the plan in comments or a design doc

### 2. Write Tests First (TDD)
- Write the test first (it will fail)
- Write minimal code to pass the test
- Refactor while keeping tests green

**Benefits:**
- Tests document intended behavior
- Forces thinking about the interface
- Prevents untested code
- Makes refactoring safer

**Coverage goals:**
- Unit tests: 80%+ coverage
- Integration tests for all critical paths
- E2E tests for main workflows

### 3. Server + Client Development
**Rule**: Every new server feature should have a corresponding client method, ideally one that's accessible via a CLI (sub)command.

### 4. Use the Makefile
Put frequently used commands in the `Makefile` for consistency:
- `make test` - Run tests
- `make lint` - Run linter
- `make dev` - Start with hot reload
- `make build-server` - Build server binary

### 5. Hot Reloading with Air
Use [Air](https://github.com/cosmtrek/air) for development with automatic rebuild on file changes.

### 6. Leverage tmux for Development
Use tmux to manage multiple terminal sessions efficiently (server, tests, logs, etc.).

## Git Workflow

### Branch Strategy
- **main**: Production-ready code, always stable
- **Feature branches**: `feature/wallet-polling`, `feature/nats-rpc`
- **Bug fixes**: `fix/jetstream-reconnect`
- **Experiments**: `experiment/timescaledb-partitioning`

### Commit Messages
Write comprehensive, descriptive commit messages that focus on the "why" rather than the "what".

**Format:**
```
[type]: Short summary (50 chars or less)

Detailed explanation of what changed and why. Wrap at 72 characters.
Include motivation, context, and any breaking changes.

- Bullet points for key changes
- Reference issues/PRs: Closes #123, Refs #456
- Note breaking changes: BREAKING: Changed API signature
```

**Types:** feat, fix, docs, refactor, test, chore, perf

## Documentation

### Always Update
When making changes, update relevant documentation:
1. **README.md**: Architecture, usage examples, getting started
2. **CHANGELOG.md**: User-facing changes
3. **Code comments**: Complex logic, public APIs, configuration options
4. **Examples**: Add/update examples in `examples/` directory

Use [Keep a Changelog](https://keepachangelog.com/) format for CHANGELOG.md.

## Code Quality

### Error Handling
**Always handle errors:**
```go
// Bad
txns, _ := client.GetTransactions(ctx)

// Good
txns, err := client.GetTransactions(ctx)
if err != nil {
    return fmt.Errorf("failed to get transactions: %w", err)
}
```

**Use structured errors** when appropriate.

### Linting
Use `golangci-lint` with strict settings. Fix all warnings before committing.

## Design Philosophy

### Make Your Dependencies Explicit
Following [go-kit](https://gokit.io/) philosophy, all dependencies should be explicit and passed as parameters. Never hide dependencies in global state, singletons, or package-level variables.

**Bad:**
```go
// Hidden dependency on global database connection
var db *sql.DB

func SaveTransaction(txn *Transaction) error {
    _, err := db.Exec("INSERT INTO transactions ...")
    return err
}
```

**Good:**
```go
// Dependency is explicit in the function signature
func SaveTransaction(ctx context.Context, db *sql.DB, txn *Transaction) error {
    _, err := db.ExecContext(ctx, "INSERT INTO transactions ...")
    return err
}

// Even better: Use constructor injection with interfaces
type TransactionStore interface {
    Save(ctx context.Context, txn *Transaction) error
}

type PostgresStore struct {
    db *sql.DB
}

func NewPostgresStore(db *sql.DB) *PostgresStore {
    return &PostgresStore{db: db}
}

// Usage: Dependencies are clear at construction time
store := NewPostgresStore(db)
poller := NewWalletPoller(solanaClient, store, natsConn)
```

**Benefits:**
- **Testability**: Easy to mock dependencies
- **Clarity**: You can see exactly what a component needs
- **Flexibility**: Swap implementations (e.g., Postgres → SQLite for tests)
- **No hidden coupling**: Dependencies are visible in type signatures
- **Lifecycle management**: Clear ownership of resources

**Apply this everywhere:**
- Constructors take dependencies as parameters
- Use interfaces for external dependencies (DB, NATS, external APIs)
- Avoid `init()` functions that set up global state
- Avoid package-level variables for stateful dependencies
- Pass `context.Context` as the first parameter to all functions

### Avoid Frameworks, Embrace the Standard Library
Frameworks hide complexity and couple code to their abstractions. Write functions that return `http.Handler` and use the standard library router.

**Handler Functions Pattern:**
Following [Mat Ryer's](https://pace.dev/blog/2018/05/09/how-I-write-http-services-after-eight-years.html) approach, write functions that return `http.Handler`:

```go
// Handler function takes dependencies and returns http.Handler
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

**Benefits:**
- Dependencies are explicit (passed as parameters)
- Easy to test (just call the function and test the handler)
- No framework magic or hidden behavior
- Handler has everything it needs in its closure

**Middleware Pattern with adaptHandler:**
Use an `adaptHandler` function to compose middleware. It iterates middleware in reverse order so the first supplied is called first:

```go
// adapter wraps a handler and returns a new handler
type adapter func(http.Handler) http.Handler

// adaptHandler applies adapters to a handler in reverse order
// so the first adapter in the list is the outermost (called first)
func adaptHandler(h http.Handler, adapters ...adapter) http.Handler {
    // Apply in reverse order
    for i := len(adapters) - 1; i >= 0; i-- {
        h = adapters[i](h)
    }
    return h
}

// Example usage:
mux.Handle("GET /wallets", adaptHandler(
    handleListWallets(store, logger),
    withRequestID(),
    withLogging(logger),
    withMetrics(promRegistry),
    withJWTAuth(jwtSecret),
))
```

**Why This Pattern Works:**
1. **Explicit Dependencies**: Handler functions receive exactly what they need
2. **Composable Middleware**: Mix and match adapters for different routes
3. **Clear Order**: First adapter in the list runs first (outer-most)
4. **No Magic**: Just functions and the stdlib - easy to understand and debug
5. **Testable**: Each handler and adapter can be tested independently

## Go Tooling Preferences

### CLI with urfave/cli
Use [urfave/cli](https://github.com/urfave/cli) for building command-line interfaces. It provides a clean, composable API for flags, commands, and subcommands.

**Benefits:**
- Clean flag/command API
- Automatic environment variable binding
- Built-in help generation
- Subcommands for different services
- Consistent CLI experience

### SQL Generation with sqlc
Use [sqlc](https://sqlc.dev/) to generate type-safe Go code from SQL. Write SQL, get Go.

**Benefits:**
- **Type Safety**: Compile-time SQL validation
- **No ORM Magic**: You write SQL, sqlc generates Go
- **Performance**: Direct SQL execution, no reflection
- **Explicit**: Generated code is readable and debuggable
- **Maintainable**: SQL is version controlled alongside code
- **PostgreSQL/TimescaleDB**: Full support for advanced features

**Why sqlc over ORMs:**
- ORMs hide complexity and make optimizations harder
- SQL is explicit and portable
- Generated code is just functions - no framework lock-in
- Easy to optimize queries without fighting the abstraction

Always regenerate sqlc code after schema changes and commit the generated code to version control.

## Unix Philosophy

### Be Quiet by Default
Programs should only output information when there's something unexpected to report. No news is good news.

**Bad:**
```
2025-10-09 10:15:23 INFO Starting wallet poller...
2025-10-09 10:15:23 INFO Connected to database
2025-10-09 10:15:23 INFO Polling wallet Abc123...
2025-10-09 10:15:23 INFO Found 0 new transactions
```

**Good:**
```
# Normal operation: Silent
# Only output on errors or significant events:
2025-10-09 10:15:23 ERROR Failed to connect to NATS: connection refused
```

### Structured Logging with slog
Use Go's built-in `slog` package for all logging. Default to DEBUG level for most log messages so verbosity can be easily controlled:

```go
// Setup logger with configurable level
func setupLogger(level slog.Level) *slog.Logger {
    opts := &slog.HandlerOptions{
        Level: level,
    }
    return slog.New(slog.NewJSONHandler(os.Stderr, opts))
}

// Usage in code - most logs at DEBUG level
logger.DebugContext(ctx, "polling wallet",
    "wallet", walletAddress,
    "last_slot", lastSlot,
)

// Only use INFO for significant lifecycle events
logger.InfoContext(ctx, "server started",
    "addr", addr,
    "version", version,
)

// WARN for recoverable issues
logger.WarnContext(ctx, "rate limit exceeded, retrying",
    "wallet", walletAddress,
    "retry_after", retryAfter,
)

// ERROR for failures
logger.ErrorContext(ctx, "failed to store transaction",
    "error", err,
    "signature", sig,
)
```

**Control verbosity via environment variable:**
Default to WARN in production, DEBUG in development via `LOG_LEVEL` env var.

### Development: Logging to Files with tee
For local development, use `tee` to write logs to both stderr and files:

```bash
# Run server with tee to log to file
./server 2>&1 | tee -a logs/server.log

# Run with debug logging enabled
LOG_LEVEL=DEBUG ./server 2>&1 | tee -a logs/server-debug.log
```

JSON logs are easily parseable with `jq`:
```bash
# Find all errors
jq 'select(.level == "ERROR")' logs/server.log

# Monitor logs in real-time
tail -f logs/server.log | jq 'select(.level == "ERROR" or .level == "WARN")'
```

### When You Write to Stdout, Use JSON
If a program produces output, make it machine-readable so it can be composed with other tools:

**Bad:**
```
Wallet: Abc123
Transactions: 5
```

**Good:**
```json
{"wallet": "Abc123", "transaction_count": 5, "last_poll": "2025-10-09T10:15:23Z"}
```

**Exceptions:**
- Interactive CLI tools can use human-friendly formatting (but offer `--json` flag)
- Error messages to stderr can be plain text
- Log files can use structured formats (JSON, logfmt)

### Practical Applications

**Backend Service:**
- Runs silently in production
- Logs errors/warnings to stderr as JSON
- Exposes metrics via Prometheus endpoint (not stdout)
- No "successfully processed transaction" logs for normal operation

**Client Library:**
- Returns errors, doesn't print them
- No "connecting to NATS..." messages
- Caller decides what to log

**CLI Tools:**
- Default to JSON output on stdout
- Provide `--format=table|json|csv` flag for human use
- Errors go to stderr
- Exit codes indicate success/failure (0 = success, non-zero = error)

## Security

- **Secrets Management**: Never commit credentials; use environment variables and _NEVER_ commit a .env file to version control!

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

## Common Tasks

### Adding a Database Migration
```bash
# Create migration files
migrate create -ext sql -dir migrations -seq add_transaction_index

# Edit migrations/000001_add_transaction_index.up.sql
# Edit migrations/000001_add_transaction_index.down.sql

# Test migration
make db-reset
make db-migrate
```

### Development Environment Setup
```bash
# Install dependencies
go mod download

# Install development tools
go install github.com/cosmtrek/air@latest
go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest

# Start dependencies (Docker Compose)
docker-compose up -d postgres nats

# Run migrations
make db-migrate

# Start development server
make dev

# Run tests
make test
```

## Summary

These principles make the system:
- **Debuggable**: JSON logs are easily parsed and analyzed
- **Composable**: Outputs become inputs for other tools
- **Scriptable**: Predictable behavior enables automation
- **Maintainable**: Simple components are easier to understand and modify
- **Resilient**: Single-purpose tools fail independently

When in doubt, ask: "Does this add essential value, or does it just add complexity?"
