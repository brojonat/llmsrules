# Releasing a Rust CLI

From conventional commits to binaries, installers and distro packages, the
way Orhun Parmaksız ships git-cliff, binsider and flawz ("just click a
button to trigger a new release", from his
[Fully Automated Releases](https://blog.orhun.dev/automated-rust-releases/)
post). The git-cliff steps were checked with git-cliff 2.14.2; the
release-plz and cargo-dist parts come from his post and repos and were not
run here.

```toml
# mise.toml
[tools]
git-cliff = "2.14.2"
release-plz = "latest"
cargo-dist = "latest"
committed = "latest"     # lints commit messages
vhs = "latest"           # records the README GIF
```

## The pipeline

1. **Conventional commits** (`feat:`, `fix:`, `docs:`, `chore(deps):`),
   enforced with `committed` (`committed.toml`) in CI.
2. **git-cliff** turns them into `CHANGELOG.md` and picks the next version.
3. **release-plz** opens a release PR (version bump + changelog) on every
   push to main; merging it publishes to crates.io and tags.
4. **cargo-dist** builds binaries and installers for the tag and creates the
   GitHub release, with git-cliff's notes as the body.
5. Dependabot keeps dependencies current; `chore(deps)` commits are left out
   of the changelog.

## git-cliff

```bash
git cliff --init                          # writes a cliff.toml to edit
git cliff -o CHANGELOG.md                 # full changelog
git cliff --unreleased --tag v0.2.0       # notes for the next release
git cliff --bumped-version                # next version from commit types
```

Checked on a scratch repo with `feat`, `fix`, `docs` and `chore(deps)`
commits: the default config groups them under `🚀 Features`,
`🐛 Bug Fixes` and `📚 Documentation`, skips `chore(deps)`, and
`--bumped-version` answers `v0.2.0` after a `feat` on top of `v0.1.0`.

## release-plz

Orhun's `release-plz.toml` lets git-cliff write the changelog and cargo-dist
create the GitHub release:

```toml
[workspace]
changelog_config = "cliff.toml"
dependencies_update = true
git_tag_enable = true
git_release_enable = false   # cargo-dist makes the GitHub release
```

## cargo-dist

`dist init` writes the config and a GitHub workflow. flawz's settings:

```toml
[workspace.metadata.dist]
installers = ["shell", "powershell", "msi"]
targets = ["aarch64-apple-darwin", "x86_64-apple-darwin", "x86_64-pc-windows-msvc", "x86_64-unknown-linux-musl"]
install-path = "CARGO_HOME"

[profile.dist]
inherits = "release"
lto = "thin"
```

Linux builds target musl, so the binary runs on any distribution. For many
more targets (riscv64, armv5te, i686), binsider and git-cliff use a
hand-rolled, tag-triggered workflow with `cross`, GPG-signed artifacts, and
`orhun/git-cliff-action` for the notes.

## Build and package

- **Commit `Cargo.lock`, and document `cargo install --locked <name>`.**
  Without `--locked`, users build with whatever dependency versions resolve
  that day.
- **Release profile** (binsider, flawz):
  ```toml
  [profile.release]
  opt-level = 3
  lto = true
  codegen-units = 1
  strip = true          # fine natively; never for wasm (see trunk.md)
  ```
- **Ship completions and a man page** from the same clap `Args`
  ([`cli.md`](cli.md#completions-and-man-pages)); distro packagers install
  them.
- **Packages**: Orhun maintains his tools in Arch Linux and Alpine himself,
  and his READMEs list every channel: `cargo install --locked`, `pacman -S`,
  `apk add`, Homebrew, Nixpkgs, binary releases. git-cliff is also on npm
  (per-platform packages, see
  [Packaging Rust Applications for the NPM Registry](https://blog.orhun.dev/packaging-rust-for-npm/))
  and PyPI (maturin).
- **Repo hygiene** shared across his projects: `cliff.toml`,
  `committed.toml`, `typos.toml`, `deny.toml` (cargo-deny: licenses and
  advisories), `rustfmt.toml`, an MSRV check in CI, and dual MIT OR
  Apache-2.0 licensing.

## The README demo

Record terminal GIFs with VHS from a `.tape` file, so they're reproducible
and re-recorded when the UI changes. Ratatui's release recipe: width 1200, a
dark theme ("don't flashbang devs with light screens"), `Hide`/`Show` around
the launch command, about 2 seconds between actions, no splash screen, and
don't commit the GIF to the repo (Ratatui's own docs embed GIFs hosted on
vhs.charm.sh, which `vhs publish` uploads to).

## Review checklist

- [ ] Are commits conventional, and checked in CI?
- [ ] Does `git cliff --unreleased` read well as release notes?
- [ ] Is `Cargo.lock` committed and the README install line `--locked`?
- [ ] Do release builds include completions and a man page?
- [ ] Is there a musl Linux binary?
- [ ] Is the README GIF generated from a VHS tape?

## Further reading

- Orhun Parmaksız, [Fully Automated Releases for Rust Projects](https://blog.orhun.dev/automated-rust-releases/).
- [git-cliff docs](https://git-cliff.org), [release-plz](https://release-plz.dev),
  [cargo-dist](https://opensource.axo.dev/cargo-dist/).
- [Ratatui: releasing your app](https://ratatui.rs/recipes/apps/release-your-app/).
