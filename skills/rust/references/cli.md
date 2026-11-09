# Command-line tools

The non-interactive half of a Rust CLI: arguments, output, errors, and the
files packagers want. For an interactive interface see [`tui.md`](tui.md);
for cutting releases see [`release.md`](release.md).

The patterns follow Orhun Parmaksız's tools (git-cliff, binsider, flawz,
systeroid) and were checked in a small reference app (`dirsize`: clap 4.6.7,
ratatui 0.30.2, Rust 1.99.1) unless marked otherwise.

## Shape

```
src/
  main.rs        parse args, call run(), map errors to an exit code
  lib.rs         pub fn run(...) and the modules: the real program
  args.rs        clap Args (in the library, so extra bins can reach it)
  bin/completions.rs, bin/mangen.rs   for packagers (below)
```

- **`main.rs` stays thin.** Everything testable lives in the library, which
  also lets another program embed it: binsider is published as a library
  whose TUI other apps can host.
- **Several frontends share a `<name>-core` crate.** git-cliff-core +
  git-cliff, systeroid-core + systeroid + systeroid-tui, tuitar-core +
  desktop + firmware. Split when the second frontend appears, not before.

## Errors and exit status

```rust
fn main() -> ExitCode {
    match run(Args::parse()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("dirsize: {e:#}"); // {:#} prints the whole context chain on one line
            ExitCode::FAILURE
        }
    }
}
```

`anyhow` with `.context(...)` in the binary; a `thiserror` enum when the
crate is also a library (Orhun's crates all define
`pub type Result<T> = std::result::Result<T, Error>` for that reason). A
missing directory prints
`dirsize: reading /nonexistent: No such file or directory (os error 2)` and
exits 1. No backtrace, no `Error: ` debug dump from returning `Result` out of
`main`.

## Arguments: clap derive

```rust
/// Show the size of each directory under a path.
#[derive(Debug, Parser)]
#[command(version, about)]
pub struct Args {
    /// Directory to scan.
    #[arg(env = "DIRSIZE_PATH", default_value = ".")]
    pub path: PathBuf,

    /// Print JSON lines instead of starting the TUI (implied when stdout is not a terminal).
    #[arg(long, env = "DIRSIZE_JSON")]
    pub json: bool,
}

#[cfg(test)]
mod tests {
    use clap::CommandFactory;

    #[test]
    fn args_are_valid() {
        super::Args::command().debug_assert(); // catches conflicting names, bad defaults
    }
}
```

clap features: `derive`, `env`, `wrap_help`. Doc comments become `--help`.

- **Every flag also reads an environment variable** (Orhun does this in every
  tool), which is how the house style wants configuration to work.
- **Name each env var explicitly, with an app prefix.** Orhun's repos use a
  bare `#[arg(env)]` with `#[command(rename_all_env = "screaming-snake")]`,
  which derives the name from the field. **A field named `path` then reads
  `$PATH`** and `user` reads `$USER` (checked: `Args { path: "/home/...bin:..." }`).
  `env = "DIRSIZE_PATH"` can't collide.
- **Closed sets of choices are `ValueEnum`**: themes, output formats, modes.
- **Verbosity is a count**: `#[arg(short, action = ArgAction::Count)] verbose: u8`,
  mapped to `info`/`debug`/`trace` (git-cliff's `-v`/`-vv`).
- **Parse before touching the terminal**, so `--help` and usage errors print
  normally rather than into a raw-mode screen.

## Output: data on stdout, people on stderr

The same binary is a TUI on a terminal and a filter in a pipe:

```rust
// Piped or asked for JSON: no TUI, one JSON object per line on stdout.
if args.json || !io::stdout().is_terminal() {
    let mut out = io::stdout().lock();
    for dir in dirs {
        let line = serde_json::json!({"path": dir, "bytes": event::dir_size(&dir)});
        if let Err(e) = writeln!(out, "{line}") {
            if e.kind() == io::ErrorKind::BrokenPipe {
                return Ok(()); // `| head` closed the pipe: done, not an error
            }
            return Err(e).context("writing to stdout");
        }
    }
    return Ok(());
}
```

Checked: `dirsize dir | cat` prints JSON lines, `| head -1` exits 0, and the
same command on a terminal opens the TUI.

- **JSON lines** (one object per line) stream and compose with `jq`, `grep`,
  `head`. Use a single JSON document only for a single result.
- **Logs, progress and spinners go to stderr** (git-cliff: tracing and
  `tracing-indicatif` on stderr, the changelog on stdout). Quiet by default.
- **`println!` panics on a closed pipe.** Rust ignores `SIGPIPE`; see
  [`signals.md`](signals.md#pipes-sigpipe-is-ignored-so-println-panics).
- **stdout is buffered, stderr isn't.** Orhun measured stderr as the slower
  stream for that reason. For heavy output, lock stdout once (as above) or
  wrap it in a `BufWriter`.

## Completions and man pages

Packagers (Orhun maintains Arch and Alpine packages) want completions and a
man page at build time. git-cliff and flawz ship them as extra binaries that
reuse the library's `Args`:

```rust
// src/bin/completions.rs
use clap::{CommandFactory, ValueEnum};
use clap_complete::Shell;
use dirsize::args::Args;

fn main() -> std::io::Result<()> {
    let out_dir = std::env::var_os("OUT_DIR").expect("set OUT_DIR");
    for &shell in Shell::value_variants() {
        clap_complete::generate_to(shell, &mut Args::command(), env!("CARGO_PKG_NAME"), &out_dir)?;
    }
    Ok(())
}
```

```rust
// src/bin/mangen.rs
use std::{fs, path::Path};

use clap::CommandFactory;
use dirsize::args::Args;

fn main() -> std::io::Result<()> {
    let out_dir = std::env::var_os("OUT_DIR").expect("set OUT_DIR");
    let mut page = Vec::new();
    clap_mangen::Man::new(Args::command()).render(&mut page)?;
    fs::write(Path::new(&out_dir).join(concat!(env!("CARGO_PKG_NAME"), ".1")), page)
}
```

With extra binaries, set `default-run = "<name>"` under `[package]` so
`cargo run` still means the app. Checked: `OUT_DIR=out cargo run --bin completions`
writes bash, zsh, fish, elvish and PowerShell files, and `man -l out/dirsize.1`
renders.

## Configuration

Flags and environment variables first. If a file is really needed, one TOML
file parsed with serde, with every key also settable by a flag. For its
location, `etcetera`'s `choose_app_strategy` follows XDG on macOS
(`~/.config/<app>`), which CLI users expect; `directories` uses
`~/Library/Application Support` there. Print the resolved path in `--version`
or `--help` so users can find it.

## Review checklist

- [ ] Is `main.rs` only parse, run, and map the error to an exit code?
- [ ] Does every env var have an explicit, app-prefixed name?
- [ ] Is there an `Args::command().debug_assert()` test?
- [ ] Does stdout carry only data (JSON lines when piped), and stderr
      everything else?
- [ ] Does `tool | head -1` exit 0?
- [ ] Do completions and a man page build from the same `Args`?

## Further reading

- Orhun Parmaksız, [Why stdout is faster than stderr?](https://blog.orhun.dev/stdout-vs-stderr/)
- [git-cliff](https://github.com/orhun/git-cliff) and
  [flawz](https://github.com/orhun/flawz): the clap, completions and mangen
  layout above.
- [clap derive tutorial](https://docs.rs/clap/latest/clap/_derive/_tutorial/index.html).
