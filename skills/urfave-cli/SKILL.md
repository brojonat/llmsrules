---
name: urfave-cli
description: Build Go command-line applications with urfave/cli v3 — commands, subcommands, flags, env var binding, Before/After hooks, shell completion, and testing. Use when creating or modifying a Go CLI entry point (main.go), adding subcommands, wiring flags to environment variables, customizing help output, or testing CLI behavior. Covers the cli.Command declarative API, flag types (StringFlag, IntFlag, BoolFlag, DurationFlag, StringSliceFlag, TimestampFlag, etc.), cli.Exit exit codes, and context.Context propagation into actions.
---

# urfave/cli (Go)

Declarative CLI framework for Go. Commands, subcommands, typed flags, env var binding, and help generation with zero dependencies outside the standard library.

## Version

Use **v3** (current stable: `v3.8.0`). Import path is `github.com/urfave/cli/v3`. v2 is mature and still maintained, but new code should target v3 — its API centers on `cli.Command` (a recursive tree) instead of the v2 split between `cli.App` and `cli.Command`, and the action signature is `func(context.Context, *cli.Command) error` rather than `func(*cli.Context) error`.

If you see existing code with `cli.App`, `cli.Context`, or `github.com/urfave/cli/v2`, that is v2. Don't mix versions in one module.

### Install

```sh
go get github.com/urfave/cli/v3@latest
```

```go
import "github.com/urfave/cli/v3"
```

## Minimal main.go

Every urfave/cli app has the same top-level shape: construct a `*cli.Command`, call `Run` with a `context.Context` and `os.Args`, exit non-zero on error.

```go
package main

import (
	"context"
	"fmt"
	"log"
	"os"

	"github.com/urfave/cli/v3"
)

func main() {
	cmd := &cli.Command{
		Name:  "greet",
		Usage: "fight the loneliness!",
		Action: func(ctx context.Context, cmd *cli.Command) error {
			fmt.Println("Hello friend!")
			return nil
		},
	}

	if err := cmd.Run(context.Background(), os.Args); err != nil {
		log.Fatal(err)
	}
}
```

`cmd.Run` does **not** call `os.Exit`. Exit codes fall through to 0 unless you return a `cli.ExitCoder` (see Exit codes below) or wrap with `log.Fatal`.

## Command metadata

The root `cli.Command` holds the app-level fields. Subcommands use the same struct.

```go
cmd := &cli.Command{
	Name:        "myapp",
	Usage:       "one-line summary shown in help",
	UsageText:   "myapp [global options] command [command options] [arguments...]",
	Description: "Long-form description. Shown under `myapp --help`.",
	Version:     "v1.2.3",
	Copyright:   "(c) 2026 Acme Inc.",
	ArgsUsage:   "[target...]",
	Authors: []any{
		"Jane Doe <jane@example.com>",
	},
	Metadata: map[string]any{
		"build": "abc123",
	},
	HideHelp:    false,
	HideVersion: false,
	Suggest:     true, // "did you mean X?" for typos
}
```

Pass the version via `-ldflags` at build time so it reflects the actual release:

```sh
go build -ldflags "-X main.version=$(git describe --tags)" ./cmd/myapp
```

```go
var version = "dev"

func main() {
	cmd := &cli.Command{Name: "myapp", Version: version /* ... */}
	_ = cmd.Run(context.Background(), os.Args)
}
```

## Commands and subcommands

Subcommands are just `*cli.Command` values nested under `Commands`. They can nest arbitrarily deep — a `template add` / `template remove` pattern is one level, `git remote add` is two.

```go
cmd := &cli.Command{
	Name: "tasks",
	Commands: []*cli.Command{
		{
			Name:    "add",
			Aliases: []string{"a"},
			Usage:   "add a task to the list",
			Action: func(ctx context.Context, cmd *cli.Command) error {
				fmt.Println("added task:", cmd.Args().First())
				return nil
			},
		},
		{
			Name:    "complete",
			Aliases: []string{"c"},
			Usage:   "complete a task on the list",
			Action: func(ctx context.Context, cmd *cli.Command) error {
				fmt.Println("completed task:", cmd.Args().First())
				return nil
			},
		},
		{
			Name:    "template",
			Aliases: []string{"t"},
			Usage:   "options for task templates",
			Commands: []*cli.Command{
				{
					Name:  "add",
					Usage: "add a new template",
					Action: func(ctx context.Context, cmd *cli.Command) error {
						fmt.Println("new template:", cmd.Args().First())
						return nil
					},
				},
				{
					Name:  "remove",
					Usage: "remove an existing template",
					Action: func(ctx context.Context, cmd *cli.Command) error {
						fmt.Println("removed template:", cmd.Args().First())
						return nil
					},
				},
			},
		},
	},
}
```

### Command categories

Group subcommands in the help output by setting `Category`:

```go
Commands: []*cli.Command{
	{Name: "noop"},
	{Name: "add", Category: "template"},
	{Name: "remove", Category: "template"},
}
```

Renders as:

```
COMMANDS:
  noop

  template:
    add
    remove
```

### Organizing larger apps

Put each subcommand in its own file and expose a constructor:

```
cmd/myapp/
  main.go
  commands/
    serve.go     // func ServeCommand() *cli.Command
    migrate.go   // func MigrateCommand() *cli.Command
    user.go      // func UserCommand() *cli.Command  (has its own sub-Commands)
```

```go
// commands/serve.go
package commands

import (
	"context"
	"github.com/urfave/cli/v3"
)

func ServeCommand() *cli.Command {
	return &cli.Command{
		Name:  "serve",
		Usage: "run the HTTP server",
		Flags: []cli.Flag{
			&cli.StringFlag{Name: "addr", Value: ":8080", Sources: cli.EnvVars("ADDR")},
		},
		Action: func(ctx context.Context, cmd *cli.Command) error {
			// start server, honor ctx cancellation
			return nil
		},
	}
}
```

```go
// main.go
cmd := &cli.Command{
	Name: "myapp",
	Commands: []*cli.Command{
		commands.ServeCommand(),
		commands.MigrateCommand(),
		commands.UserCommand(),
	},
}
```

## Flags

Flags are declared on a `cli.Command` via the `Flags` slice. Flags on the root are global; flags on a subcommand are local to that subcommand. Read them in the Action with `cmd.String("name")`, `cmd.Int("name")`, `cmd.Bool("name")`, `cmd.Duration("name")`, `cmd.StringSlice("name")`, etc.

### Basic types

```go
cmd := &cli.Command{
	Flags: []cli.Flag{
		&cli.StringFlag{
			Name:    "lang",
			Aliases: []string{"l"},
			Value:   "english",       // default
			Usage:   "language for the greeting",
		},
		&cli.IntFlag{
			Name:  "port",
			Value: 8080,
			Usage: "listen port",
		},
		&cli.BoolFlag{
			Name:  "verbose",
			Usage: "enable verbose logging",
		},
		&cli.DurationFlag{
			Name:  "timeout",
			Value: 30 * time.Second,
			Usage: "request timeout",
		},
		&cli.FloatFlag{
			Name:  "ratio",
			Value: 0.5,
		},
		&cli.StringSliceFlag{
			Name:  "tag",
			Usage: "tags (can be repeated)",
		},
		&cli.IntSliceFlag{
			Name: "port-list",
		},
	},
	Action: func(ctx context.Context, cmd *cli.Command) error {
		fmt.Println("lang:", cmd.String("lang"))
		fmt.Println("port:", cmd.Int("port"))
		fmt.Println("verbose:", cmd.Bool("verbose"))
		fmt.Println("timeout:", cmd.Duration("timeout"))
		fmt.Println("ratio:", cmd.Float("ratio"))
		fmt.Println("tags:", cmd.StringSlice("tag"))
		fmt.Println("ports:", cmd.IntSlice("port-list"))
		return nil
	},
}
```

**Full set of basic flag types:** `StringFlag`, `BoolFlag`, `IntFlag` (plus `Int8/16/32/64Flag`), `UintFlag` (plus `Uint8/16/32/64Flag`), `FloatFlag` (plus `Float32/64Flag`), `DurationFlag`, `TimestampFlag`.

**Slice flags:** `StringSliceFlag`, `IntSliceFlag` (plus `Int8/16/32/64SliceFlag`), `UintSliceFlag` (plus `Uint8/16/32/64SliceFlag`), `FloatSliceFlag`. Slice flags are repeatable on the command line: `--tag a --tag b --tag c`.

### Timestamp flags

```go
&cli.TimestampFlag{
	Name: "meeting",
	Config: cli.TimestampConfig{
		Layouts:  []string{"2006-01-02T15:04:05"},
		Timezone: time.Local, // optional; defaults to UTC
	},
}
// Use: myapp --meeting 2026-04-17T09:00:00
// Read: cmd.Timestamp("meeting") returns time.Time
```

### Aliases

```go
&cli.StringFlag{
	Name:    "config",
	Aliases: []string{"c", "cfg"},
	Usage:   "config file path",
}
// Equivalent: --config foo.yaml / -c foo.yaml / --cfg foo.yaml
```

### Required flags

```go
&cli.StringFlag{
	Name:     "token",
	Usage:    "API token",
	Required: true,
}
// Missing it yields: `Required flag "token" not set`
```

### Destination binding

Write the parsed value directly into a variable instead of calling `cmd.String(...)` later:

```go
var language string

cmd := &cli.Command{
	Flags: []cli.Flag{
		&cli.StringFlag{
			Name:        "lang",
			Value:       "english",
			Destination: &language,
		},
	},
	Action: func(ctx context.Context, cmd *cli.Command) error {
		fmt.Println("lang:", language)
		return nil
	},
}
```

### Help-output default text

Use `DefaultText` when the real default is runtime-computed or zero-but-meaningful:

```go
&cli.IntFlag{
	Name:        "port",
	Value:       0,
	DefaultText: "random",
	Usage:       "listen port",
}
// Help shows: --port value  listen port (default: random)
```

### Placeholder in usage

Back-quoted words in `Usage` become the placeholder shown in help:

```go
&cli.StringFlag{
	Name:    "config",
	Aliases: []string{"c"},
	Usage:   "Load configuration from `FILE`",
}
// Help: --config FILE, -c FILE   Load configuration from FILE
```

### Per-flag validators

Run validation at parse time (before `Action`):

```go
&cli.IntFlag{
	Name: "longdistance",
	Validator: func(v int) error {
		if v < 10 {
			return fmt.Errorf("10 miles isn't long distance!")
		}
		return nil
	},
}
```

### Per-flag action (post-parse hook)

```go
&cli.IntFlag{
	Name: "port",
	Action: func(ctx context.Context, cmd *cli.Command, v int) error {
		if v >= 65536 {
			return fmt.Errorf("port %d out of range [0-65535]", v)
		}
		return nil
	},
}
```

### Bool count flag (`-vvv`)

```go
var verbosity int

cmd := &cli.Command{
	UseShortOptionHandling: true, // required for -vvv (combined shorts)
	Flags: []cli.Flag{
		&cli.BoolFlag{
			Name:    "verbose",
			Aliases: []string{"v"},
			Config:  cli.BoolConfig{Count: &verbosity},
		},
	},
	Action: func(ctx context.Context, cmd *cli.Command) error {
		fmt.Println("verbosity:", verbosity) // -vvv => 3
		return nil
	},
}
```

When `UseShortOptionHandling` is on, you cannot use single-dash long flags like `-option` — only `--option` or true shorts.

### Mutually exclusive flag groups

```go
MutuallyExclusiveFlags: []cli.MutuallyExclusiveFlags{
	{
		Required: true,
		Flags: [][]cli.Flag{
			{&cli.StringFlag{Name: "login"}},
			{&cli.StringFlag{Name: "id"}},
		},
	},
}
// Error if neither or both: "one of these flags needs to be provided: login, id"
```

## Environment variable binding (Sources)

In v3, env vars are one of several "value sources" exposed via the `Sources` field. (v2's `EnvVars: []string{...}` is gone.)

```go
&cli.StringFlag{
	Name:    "lang",
	Value:   "english",
	Sources: cli.EnvVars("APP_LANG"),
}
```

Multiple env vars — first one that resolves wins:

```go
Sources: cli.EnvVars("LEGACY_COMPAT_LANG", "APP_LANG", "LANG")
```

From a file:

```go
&cli.StringFlag{
	Name:    "password",
	Sources: cli.Files("/etc/mysql/password"),
}
```

Chain multiple sources — evaluated in declaration order, first match wins:

```go
&cli.StringFlag{
	Name: "token",
	Sources: cli.NewValueSourceChain(
		cli.EnvVar("APP_TOKEN"),
		cli.File("/etc/myapp/token"),
	),
}
```

### Structured config files (YAML/JSON/TOML)

Use the companion module `github.com/urfave/cli-altsrc/v3`:

```go
import (
	altsrc "github.com/urfave/cli-altsrc/v3"
	altsrcyaml "github.com/urfave/cli-altsrc/v3/yaml"
)

&cli.StringFlag{
	Name:    "password",
	Sources: cli.NewValueSourceChain(
		altsrcyaml.YAML("db.password", altsrc.StringSourcer("/etc/myapp/config.yaml")),
	),
}
```

Lazy-load based on another flag (the `--config` flag determines the file path):

```go
var cfgPath string

cmd := &cli.Command{
	Flags: []cli.Flag{
		&cli.StringFlag{
			Name:        "config",
			Aliases:     []string{"c"},
			Value:       "/etc/myapp/config.yaml",
			Destination: &cfgPath,
		},
		&cli.StringFlag{
			Name: "password",
			Sources: cli.NewValueSourceChain(
				altsrcyaml.YAML("db.password", altsrc.NewStringPtrSourcer(&cfgPath)),
			),
		},
	},
}
```

## Action functions

The Action signature is:

```go
func(ctx context.Context, cmd *cli.Command) error
```

- `ctx` is the `context.Context` threaded through from `cmd.Run(ctx, os.Args)`. Propagate it to downstream calls (HTTP clients, DB drivers, goroutines) so `SIGINT` or caller cancellation flows all the way through.
- `cmd` is the `*cli.Command` that matched — typically the deepest one, i.e. the subcommand being run. Read flags off it.
- Return `nil` for success, a regular `error` for a generic failure, or `cli.Exit(msg, code)` to control the process exit code.

```go
Action: func(ctx context.Context, cmd *cli.Command) error {
	addr := cmd.String("addr")
	timeout := cmd.Duration("timeout")

	reqCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	req, err := http.NewRequestWithContext(reqCtx, "GET", addr, nil)
	if err != nil {
		return fmt.Errorf("build request: %w", err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("do request: %w", err)
	}
	defer resp.Body.Close()
	fmt.Println("status:", resp.Status)
	return nil
}
```

### Reading flags from the right command

`cmd.String(...)` looks up the flag on this command, then walks up the lineage (parent, grandparent, root). That means **global flags set on the root are visible from any subcommand's Action.** Call `cmd.Root()` to explicitly target the root, or `cmd.IsSet("flag")` to see if a flag was actually set (vs. default).

```go
Action: func(ctx context.Context, cmd *cli.Command) error {
	// global flag from root
	verbose := cmd.Bool("verbose")

	// local flag on this subcommand
	addr := cmd.String("addr")

	// check if user explicitly set it
	if cmd.IsSet("timeout") {
		// ...
	}
	return nil
}
```

### Positional arguments

Typed positional args (new in v3) via `Arguments`:

```go
cmd := &cli.Command{
	Arguments: []cli.Argument{
		&cli.IntArg{Name: "count"},
		&cli.StringArgs{Name: "files", Min: 1, Max: -1}, // -1 = unbounded
	},
	Action: func(ctx context.Context, cmd *cli.Command) error {
		count := cmd.IntArg("count")
		files := cmd.StringArgs("files")
		fmt.Println(count, files)
		return nil
	},
}
```

Types: `StringArg/Args`, `IntArg/Args` (+ sized), `UintArg/Args` (+ sized), `FloatArg/Args`, `TimestampArg/Args`. Use `Args` (plural) for multi-value, with `Min`/`Max` bounds.

Untyped positional args (always available) via `cmd.Args()`:

```go
Action: func(ctx context.Context, cmd *cli.Command) error {
	fmt.Println("n:", cmd.Args().Len())
	fmt.Println("first:", cmd.Args().First())
	fmt.Println("third:", cmd.Args().Get(2))
	fmt.Println("rest:", cmd.Args().Tail())
	fmt.Println("any?", cmd.Args().Present())
	fmt.Println("slice:", cmd.Args().Slice())
	return nil
}
```

## Before / After / CommandNotFound hooks

Lifecycle callbacks fire around a command's Action. Defined on any `cli.Command` node.

```go
cmd := &cli.Command{
	Before: func(ctx context.Context, cmd *cli.Command) (context.Context, error) {
		// Runs before Action (and before subcommand dispatch).
		// Returned context replaces the one passed to Action; return nil to keep current.
		logger := slog.New(/*...*/)
		ctx = context.WithValue(ctx, loggerKey{}, logger)
		return ctx, nil
	},
	After: func(ctx context.Context, cmd *cli.Command) error {
		// Runs after Action, even on error.
		return nil
	},
	CommandNotFound: func(ctx context.Context, cmd *cli.Command, name string) {
		fmt.Fprintf(cmd.Root().Writer, "no such command: %q\n", name)
	},
	OnUsageError: func(ctx context.Context, cmd *cli.Command, err error, isSubcommand bool) error {
		fmt.Fprintf(cmd.Root().Writer, "usage error: %v\n", err)
		return err
	},
	Action: /* ... */,
}
```

**`Before` is the right place** for logger setup, config loading, auth token resolution, opening a DB connection, and similar cross-cutting setup. Stash things on `ctx` via `context.WithValue`, then pull them out in subcommand Actions.

**`After` runs regardless of Action error**, so use it for cleanup (close DB, flush traces).

## Error handling and exit codes

`cmd.Run` returns the error; it does not call `os.Exit`. The simplest idiom uses `log.Fatal`, which prints and exits 1:

```go
if err := cmd.Run(context.Background(), os.Args); err != nil {
	log.Fatal(err)
}
```

For controlled exit codes, return `cli.Exit(message, code)` from your Action. `cli.Exit` implements `cli.ExitCoder`, and urfave/cli will print the message and call `os.Exit(code)` when you invoke `cli.HandleExitCoder` (which `Run` does automatically for this specific interface):

```go
Action: func(ctx context.Context, cmd *cli.Command) error {
	if !cmd.Bool("ginger-crouton") {
		return cli.Exit("Ginger croutons are not in the soup", 86)
	}
	return nil
}
```

Wrap exit-coded errors with your own type for richer control:

```go
type exitErr struct {
	msg  string
	code int
}

func (e *exitErr) Error() string { return e.msg }
func (e *exitErr) ExitCode() int { return e.code }

// return &exitErr{msg: "db unreachable", code: 3}
```

Idiomatic main that preserves exit codes:

```go
func main() {
	if err := cmd.Run(context.Background(), os.Args); err != nil {
		// cli.Exit errors already printed themselves; print others to stderr.
		var ec cli.ExitCoder
		if errors.As(err, &ec) {
			os.Exit(ec.ExitCode())
		}
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
```

## Signal handling

Wire `SIGINT`/`SIGTERM` into the root context so Ctrl-C cancels in-flight work:

```go
func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if err := cmd.Run(ctx, os.Args); err != nil {
		log.Fatal(err)
	}
}
```

Inside Actions, always pass `ctx` into anything blocking (HTTP, sql, time.After → use `time.NewTimer` + `<-ctx.Done()`).

## Help text customization

The generated help covers most needs. Tune it via:

- `Usage`, `UsageText`, `Description`, `ArgsUsage` on each command.
- **Templates**: package vars `cli.RootCommandHelpTemplate`, `cli.CommandHelpTemplate`, `cli.SubcommandHelpTemplate`. Replace or append:

```go
cli.RootCommandHelpTemplate = fmt.Sprintf(`%s

WEBSITE: https://example.com
SUPPORT: support@example.com
`, cli.RootCommandHelpTemplate)
```

- **Full override** via `cli.HelpPrinter`:

```go
cli.HelpPrinter = func(w io.Writer, templ string, data any) {
	fmt.Fprintln(w, "custom help output")
}
```

- **Custom help flag**: reassign `cli.HelpFlag` at init time.

```go
cli.HelpFlag = &cli.BoolFlag{Name: "halp", Aliases: []string{"?"}}
```

- **Suggestions**: `Suggest: true` on a command enables "did you mean X?" for typos.
- **Hide commands/flags**: `Hidden: true` on a `*cli.Command`, `Hidden: true` on any flag type.

## Shell completion

Dynamic completion for bash, zsh, fish, and PowerShell is built in. Enable it on the root command:

```go
cmd := &cli.Command{
	Name:                  "greet",
	EnableShellCompletion: true,
	Commands:              /* ... */,
}
```

At that point, `greet completion bash` (or `zsh`/`fish`/`powershell`) emits a shell script. Users source it:

```sh
# Bash (one-off)
source <(greet completion bash)

# Bash (persistent)
greet completion bash > /etc/bash_completion.d/greet

# Zsh (persistent — add to ~/.zshrc)
PROG=greet source /path/to/greet_completion.zsh
```

Custom completion logic per command:

```go
&cli.Command{
	Name: "deploy",
	ShellComplete: func(ctx context.Context, cmd *cli.Command) {
		// print one suggestion per line to cmd.Root().Writer
		for _, env := range []string{"staging", "production"} {
			fmt.Fprintln(cmd.Root().Writer, env)
		}
	},
}
```

## Context propagation

v3 unifies the `cli.Context` (v2) into `context.Context` + `*cli.Command`. This means:

- Callers control cancellation by passing their own `context.Context` into `cmd.Run`.
- Actions receive that same context and should pass it down.
- `Before` can return a **replacement** context to add values (logger, DB handle, request ID) visible to all nested Before/Action/After calls.

```go
type ctxKey string

const loggerKey ctxKey = "logger"

Before: func(ctx context.Context, cmd *cli.Command) (context.Context, error) {
	logger := slog.New(slog.NewJSONHandler(os.Stderr, nil))
	return context.WithValue(ctx, loggerKey, logger), nil
},
Action: func(ctx context.Context, cmd *cli.Command) error {
	logger := ctx.Value(loggerKey).(*slog.Logger)
	logger.Info("running", "addr", cmd.String("addr"))
	return nil
},
```

## Common patterns

### Global flags shared by all subcommands

Put them on the root; read them from any Action via flag-lookup walking.

```go
cmd := &cli.Command{
	Name: "myapp",
	Flags: []cli.Flag{
		&cli.StringFlag{Name: "log-level", Value: "info", Sources: cli.EnvVars("LOG_LEVEL")},
		&cli.StringFlag{Name: "config", Aliases: []string{"c"}, Sources: cli.EnvVars("MYAPP_CONFIG")},
	},
	Before: func(ctx context.Context, cmd *cli.Command) (context.Context, error) {
		lvl := cmd.String("log-level")
		logger := makeLogger(lvl)
		return context.WithValue(ctx, loggerKey, logger), nil
	},
	Commands: []*cli.Command{
		serveCommand(),
		migrateCommand(),
	},
}
```

### Config file loading pattern

Use the `Before` hook to parse the config once, then stash the struct on `ctx`:

```go
type cfgKey struct{}

type Config struct {
	Addr    string
	DBURL   string
}

Before: func(ctx context.Context, cmd *cli.Command) (context.Context, error) {
	path := cmd.String("config")
	cfg, err := loadConfig(path) // your YAML/JSON/TOML loader
	if err != nil {
		return ctx, fmt.Errorf("load config %q: %w", path, err)
	}
	return context.WithValue(ctx, cfgKey{}, cfg), nil
},
Action: func(ctx context.Context, cmd *cli.Command) error {
	cfg := ctx.Value(cfgKey{}).(*Config)
	// ...
	return nil
}
```

### Twelve-factor env binding

Every flag also honors an env var with a predictable prefix:

```go
func envFlag(name, env, def, usage string) *cli.StringFlag {
	return &cli.StringFlag{
		Name:    name,
		Value:   def,
		Usage:   usage,
		Sources: cli.EnvVars("MYAPP_" + env),
	}
}

Flags: []cli.Flag{
	envFlag("addr", "ADDR", ":8080", "listen address"),
	envFlag("db-url", "DB_URL", "", "Postgres connection string"),
}
```

### JSON output flag (machine-readable vs. human)

```go
&cli.StringFlag{
	Name:  "format",
	Value: "table",
	Usage: "output format (table|json|csv)",
}

// In action:
switch cmd.String("format") {
case "json":
	_ = json.NewEncoder(os.Stdout).Encode(result)
default:
	printTable(os.Stdout, result)
}
```

### Unix-style quiet defaults

Write data to stdout, logs/errors to stderr, only print on events or errors. Exit 0 on success, non-zero on failure. urfave/cli stays out of the way by default.

## Testing CLI commands

Because `*cli.Command` is a plain struct and `Run` takes a context + args slice, unit tests don't need subprocesses. Redirect `Writer` and `ErrWriter` to buffers and call `Run`.

```go
package main

import (
	"bytes"
	"context"
	"strings"
	"testing"

	"github.com/urfave/cli/v3"
)

func TestGreet(t *testing.T) {
	var out bytes.Buffer

	cmd := &cli.Command{
		Name:      "greet",
		Writer:    &out,
		ErrWriter: &out,
		Flags: []cli.Flag{
			&cli.StringFlag{Name: "name", Value: "world"},
		},
		Action: func(ctx context.Context, cmd *cli.Command) error {
			_, err := cmd.Writer.Write([]byte("hello " + cmd.String("name") + "\n"))
			return err
		},
	}

	if err := cmd.Run(context.Background(), []string{"greet", "--name", "claude"}); err != nil {
		t.Fatalf("run: %v", err)
	}
	if got, want := out.String(), "hello claude\n"; !strings.Contains(got, want) {
		t.Errorf("output = %q, want contains %q", got, want)
	}
}
```

### Table-driven CLI tests

```go
func TestCommands(t *testing.T) {
	cases := []struct {
		name    string
		args    []string
		env     map[string]string
		want    string
		wantErr string
	}{
		{name: "add", args: []string{"app", "add", "laundry"}, want: "added: laundry"},
		{name: "missing required", args: []string{"app", "login"}, wantErr: `Required flag "user" not set`},
		{name: "via env", env: map[string]string{"APP_USER": "alice"}, args: []string{"app", "login"}, want: "hi alice"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			for k, v := range tc.env {
				t.Setenv(k, v)
			}
			var out bytes.Buffer
			cmd := newRootCommand() // your constructor
			cmd.Writer = &out
			cmd.ErrWriter = &out

			err := cmd.Run(context.Background(), tc.args)
			if tc.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), tc.wantErr) {
					t.Fatalf("err = %v, want contains %q", err, tc.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatalf("run: %v", err)
			}
			if !strings.Contains(out.String(), tc.want) {
				t.Errorf("output = %q, want contains %q", out.String(), tc.want)
			}
		})
	}
}
```

### Testing exit codes

Intercept exits by replacing `cli.OsExiter` (which `cli.HandleExitCoder` calls) with a test double, or check the returned error directly:

```go
func TestExitCode(t *testing.T) {
	cmd := &cli.Command{
		Action: func(ctx context.Context, cmd *cli.Command) error {
			return cli.Exit("boom", 42)
		},
	}
	err := cmd.Run(context.Background(), []string{"app"})
	var ec cli.ExitCoder
	if !errors.As(err, &ec) {
		t.Fatalf("err %v does not implement ExitCoder", err)
	}
	if ec.ExitCode() != 42 {
		t.Fatalf("code = %d, want 42", ec.ExitCode())
	}
}
```

## Full worked example

A realistic root-command scaffold pulling the patterns together:

```go
// cmd/myapp/main.go
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/urfave/cli/v3"
)

var version = "dev" // set via -ldflags

type loggerCtxKey struct{}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	cmd := &cli.Command{
		Name:    "myapp",
		Usage:   "example service and CLI",
		Version: version,
		Flags: []cli.Flag{
			&cli.StringFlag{
				Name:    "log-level",
				Value:   "info",
				Sources: cli.EnvVars("MYAPP_LOG_LEVEL"),
				Usage:   "log level (debug|info|warn|error)",
			},
		},
		Before: func(ctx context.Context, cmd *cli.Command) (context.Context, error) {
			logger := slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{
				Level: parseLevel(cmd.String("log-level")),
			}))
			return context.WithValue(ctx, loggerCtxKey{}, logger), nil
		},
		EnableShellCompletion: true,
		Suggest:               true,
		Commands: []*cli.Command{
			serveCommand(),
			migrateCommand(),
		},
	}

	if err := cmd.Run(ctx, os.Args); err != nil {
		var ec cli.ExitCoder
		if errors.As(err, &ec) {
			os.Exit(ec.ExitCode())
		}
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func serveCommand() *cli.Command {
	return &cli.Command{
		Name:  "serve",
		Usage: "run the HTTP server",
		Flags: []cli.Flag{
			&cli.StringFlag{
				Name:    "addr",
				Value:   ":8080",
				Sources: cli.EnvVars("MYAPP_ADDR"),
			},
			&cli.DurationFlag{
				Name:  "shutdown-timeout",
				Value: 10 * time.Second,
			},
		},
		Action: func(ctx context.Context, cmd *cli.Command) error {
			logger := ctx.Value(loggerCtxKey{}).(*slog.Logger)
			logger.Info("starting", "addr", cmd.String("addr"))
			<-ctx.Done()
			return cli.Exit("shutdown", 0)
		},
	}
}

func migrateCommand() *cli.Command {
	return &cli.Command{
		Name:  "migrate",
		Usage: "run database migrations",
		Flags: []cli.Flag{
			&cli.StringFlag{
				Name:     "db-url",
				Required: true,
				Sources:  cli.EnvVars("MYAPP_DB_URL"),
			},
		},
		Action: func(ctx context.Context, cmd *cli.Command) error {
			// ... run migrations
			return nil
		},
	}
}

func parseLevel(s string) slog.Level {
	switch s {
	case "debug":
		return slog.LevelDebug
	case "warn":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}
```

## Quick reference

| Need | API |
|---|---|
| Root command / app | `&cli.Command{Name, Usage, Version, Action}` |
| Run | `cmd.Run(ctx, os.Args)` |
| Subcommand tree | `Commands: []*cli.Command{...}` (nest freely) |
| Action signature | `func(ctx context.Context, cmd *cli.Command) error` |
| Read flag | `cmd.String("x")`, `cmd.Int`, `cmd.Bool`, `cmd.Duration`, `cmd.StringSlice`, ... |
| Was flag set? | `cmd.IsSet("x")` |
| Positional args | `cmd.Args().First()/Get(i)/Tail()/Len()/Slice()` or typed `Arguments` + `cmd.IntArg` etc. |
| Env var binding | `Sources: cli.EnvVars("APP_X", "LEGACY_X")` |
| File source | `Sources: cli.Files("/etc/app/x")` |
| Chain sources | `Sources: cli.NewValueSourceChain(cli.EnvVar(...), cli.File(...))` |
| Required flag | `Required: true` |
| Alias | `Aliases: []string{"x"}` |
| Mutually exclusive | `MutuallyExclusiveFlags: []cli.MutuallyExclusiveFlags{...}` |
| Exit with code | `return cli.Exit("msg", 2)` |
| Before/After | `Before func(ctx,*cli.Command) (context.Context,error)`, `After func(ctx,*cli.Command) error` |
| Shell completion | `EnableShellCompletion: true`, then `myapp completion bash\|zsh\|fish\|powershell` |
| Customize help | `cli.RootCommandHelpTemplate`, `cli.HelpPrinter`, `cli.HelpFlag` |
| Did-you-mean | `Suggest: true` |
| Testing | Set `cmd.Writer`/`cmd.ErrWriter` to buffers, call `cmd.Run(ctx, args)` |

## Pitfalls

- **v2 vs v3 mix-up.** `cli.App`, `cli.Context`, `EnvVars: []string{...}`, and `Subcommands` are v2-only. Don't combine with `/v3` imports.
- **`cmd.Run` doesn't exit.** You must propagate the error to `log.Fatal` or `os.Exit` yourself. A missing check silently swallows failures.
- **Global flag reads from subcommand.** `cmd.String("x")` walks up the lineage, but `cmd.LocalFlagNames()` only lists this level's. Use `cmd.Root().String("x")` to force root lookup.
- **`UseShortOptionHandling` breaks `-longname`.** Single-dash long flags stop parsing. Use `--longname` or short aliases only.
- **`BeforeFunc` returns `(context.Context, error)`.** Returning `nil` for the context is fine (keeps current); returning a non-nil value replaces it for nested calls.
- **Slice flags append, not overwrite.** `--tag a --tag b` yields `["a","b"]`. If a default is set, explicit values replace the default entirely.
- **Timestamp layout is required.** `TimestampFlag` has no default layout; set `Config.Layouts`.
- **`cli.Exit` prints to `cli.ErrWriter` (default `os.Stderr`), not to your logger.** Redirect `ErrWriter` in tests.
