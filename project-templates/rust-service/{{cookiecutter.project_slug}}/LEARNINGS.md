# Learnings

Pitfalls found the hard way. Each entry: what happened, why it was
surprising, how to avoid it.

## rust-analyzer "is installed" but isn't

`~/.cargo/bin/rust-analyzer` exists after installing rustup, but it's only a
proxy; running it fails with `Unknown binary 'rust-analyzer' in official
toolchain` until the component is added. Editors then show no diagnostics
with no obvious error. `rust-toolchain.toml` lists the component, so any
cargo command in this repo installs it.

## rustaceanvim needs a recent Neovim

Current rustaceanvim refuses to load on Neovim 0.11 ("requires Neovim 0.12
or above"), which looks like rust-analyzer silently not attaching. Use
Neovim 0.12+.
