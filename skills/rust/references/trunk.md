# Building and shipping wasm apps with Trunk

[Trunk](https://trunk-rs.github.io/trunk/guide) bundles a Rust crate into a
static web app: an `index.html`, a `.js` loader and a `.wasm` file. What the
code inside can and can't do in a browser is in [`wasm.md`](wasm.md).

Everything here was checked against Trunk 0.22.1, Rust 1.99.1 and headless
Chromium unless it says otherwise.

## What `trunk build` does

1. Reads `index.html` and plans the assets marked `data-trunk`.
2. Runs `cargo build --target wasm32-unknown-unknown`.
3. Runs the `wasm-bindgen` CLI to generate the JS glue. Trunk picks the CLI
   version that matches `wasm-bindgen` in `Cargo.lock` and downloads it into
   `~/.cache/trunk`, so CLI/library mismatches don't happen.
4. In `--release` builds, runs `wasm-opt`, **if the page asks for it** (below).
5. Writes everything to `dist/` with content hashes in the file names, and
   rewrites `index.html` to load them with `integrity` (SRI) attributes.

## Install

mise pins Trunk next to everything else. **The registry shorthand `trunk` is
a different tool**: it resolves to `npm:@trunkio/launcher`, the trunk.io
linter (versions 1.3.x). Name the GitHub backend explicitly:

```toml
[tools]
"github:trunk-rs/trunk" = "0.22.1"
```

The Rust toolchain and the `wasm32-unknown-unknown` target come from
`rust-toolchain.toml`; see [`wasm.md`](wasm.md#target-and-toolchain).

## A minimal app

```toml
# Cargo.toml
[package]
name = "web"
version = "0.1.0"
edition = "2024"

[dependencies]
console_error_panic_hook = "0.1"
wasm-bindgen = "0.2"
web-sys = { version = "0.3", features = ["Window", "Document", "HtmlElement", "Text"] }

[profile.release]
opt-level = "z"     # optimize for size
lto = true
codegen-units = 1
panic = "abort"
# NOT strip = true: it breaks wasm-opt (below)
```

```html
<!-- index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>web</title>
  <link data-trunk rel="rust" data-wasm-opt="z"/>
</head>
<body></body>
</html>
```

```rust
// src/main.rs
use web_sys::window;

fn main() {
    console_error_panic_hook::set_once();
    let doc = window().and_then(|w| w.document()).expect("no document");
    let body = doc.body().expect("no body");
    body.append_child(&doc.create_text_node("hello from rust")).expect("append");
}
```

A plain `fn main` is the entry point; no `#[wasm_bindgen(start)]` is needed.

### Always write the `rel="rust"` link

The guide calls the link optional, and the app builds without it, but **the
implicit pipeline turns wasm-opt off, even in `--release`**. In Trunk's
source, a missing link means `WasmOptLevel::Off`, while a bare link defaults
to `-O` in release builds. Measured on the hello world above:

| Build | `.wasm` | gzipped |
|---|---|---|
| `trunk build` (debug) | 292 KB | |
| `--release`, no `rel="rust"` link | 51.5 KB | 15.6 KB |
| `--release`, bare link (wasm-opt `-O`) | 24.7 KB | |
| `--release`, `data-wasm-opt="z"` | 24.7 KB | 11.1 KB |
| ... plus the `[profile.release]` above | 22.6 KB | 10.5 KB |

### Don't set `strip = true`

`strip = true` removes the wasm `target_features` section. wasm-bindgen warns
(`the target_features custom section is missing, likely due to strip = true`),
and wasm-opt then rejects the module and **fails the release build**:

```
[wasm-validator error in function 2] unexpected false: memory.copy operations require bulk memory operations [--enable-bulk-memory-opt]
Fatal: error validating input
```

wasm-opt already strips what's worth stripping.

## Configuration: `Trunk.toml`

Trunk reads `Trunk.toml` (or `.trunk.toml`, `Trunk.yaml`, `Trunk.json`, or
`[package.metadata.trunk]` in `Cargo.toml`). CLI flags and `TRUNK_<SECTION>_<ITEM>`
environment variables override it. `trunk config show` prints the result.

```toml
trunk-version = "^0.22"     # refuse to build with an older Trunk

[serve]
port = 8081                 # the backend keeps 8080

[watch]
ignore = ["logs/**"]        # see "the rebuild loop" below

[[proxy]]                   # dev only: /api/* goes to the axum service
backend = "http://127.0.0.1:8080/api/"
```

### The rebuild loop: `logs/` inside the project

`trunk serve` watches the directory containing `index.html`. The dev task
tees its output to `logs/`, which is inside that directory, so **every log
line written triggers a rebuild, which writes more log lines**. Measured: 115
builds in 30 seconds with nothing edited.

The obvious fix doesn't work. Trunk joins each `ignore` entry onto the project
root and matches it as a **glob** against the absolute path of each changed
file. `ignore = ["logs"]` therefore matches only the directory itself, not
`logs/trunk.log` (still 77 builds in 20 seconds). Use `"logs/**"`. Checked,
including through the `dev-web` task below: a build or two at startup, then
exactly one per real edit.

Two related watcher facts:

- **Only content changes count.** `touch` (a metadata change) doesn't trigger
  a rebuild; Trunk only acts on data, rename, create and remove events.
- **Only the `index.html` directory is watched by default.** A frontend crate
  that depends on a sibling crate (`../shared`) won't rebuild when that crate
  changes. List it: `watch = [".", "../shared"]`. (From Trunk's source: watch
  paths default to the target HTML's parent directory.)

## The dev loop

```toml
# mise.toml
[tasks.dev-web]
description = "trunk serve with autoreload, tee to logs/trunk.log"
run = 'mkdir -p logs; f() { trunk serve "$@" 2>&1 | tee logs/trunk.log; }; f'
```

- **Trunk logs to stdout, cargo to stderr.** `2>&1` is what puts compile
  errors in the log file.
- **Autoreload reloads the whole page** over a WebSocket (`location.reload()`
  in the injected script). There's no hot module replacement, so
  client-side state is lost on every rebuild.
- **The dev server answers every unknown path with `index.html` and a 200**,
  including asset paths like `/nope.png`. That's what lets client-side
  routes survive a reload, but it also means a typo in an asset path shows up
  as a parse error or a blank image, never as a 404.
- **The proxy forwards** method, headers, body and query string. Proxy
  config on the CLI (`--proxy-backend`) replaces every `[[proxy]]` in
  `Trunk.toml`.

Run the backend in a second task (the `rust-service` template's `dev`) and
open the Trunk port. Requests to `/api/*` reach the backend with no CORS
setup, the same as in production below.

## Production builds

```bash
trunk build --release --locked
```

`--locked` fails the build if `Cargo.lock` is out of date, as `cargo --locked`
does. The output in `dist/` is static files: `index.html`, `<name>-<hash>.js`,
`<name>-<hash>_bg.wasm`, and any other assets.

**Asset URLs are absolute.** The generated `index.html` loads `/web-<hash>.js`,
so the app only works served from the site root. To serve it under a
subpath, build with that prefix. Checked: a default build copied to `/app/`
gets 404s for the `.js` and `.wasm`, and `--public-url /app/` works there:

```bash
trunk build --release --public-url /app/
```

The app can read the prefix at runtime from `document.baseURI` after adding
`<base data-trunk-public-url/>` to `<head>`, which a client-side router needs.

## Shipping

### From the axum service (one binary, one origin)

The simplest deploy is for the backend to serve `dist/` itself: no second
server, no CORS, and `/api` stays on the same origin as in dev. Checked with
axum 0.8.9 and tower-http 0.7.1 (features `fs`, `set-header`):

```rust
use axum::{Json, Router, http::{HeaderValue, StatusCode, header}, routing::get};
use tower_http::{
    services::{ServeDir, ServeFile},
    set_header::SetResponseHeaderLayer,
};

/// `/api` is the backend; everything else is the Trunk build in `dist`.
fn app(dist: &std::path::Path) -> Router {
    let api = Router::new()
        .route("/health", get(|| async { Json(serde_json::json!({"ok": true})) }))
        .fallback(|| async { StatusCode::NOT_FOUND }); // API typos must not get index.html

    // Unknown paths get index.html so client-side routes survive a reload.
    // no-cache = revalidate every time (cheap 304 via ETag), so a deploy is
    // picked up at once; the hashed .js/.wasm names change on every build anyway.
    let spa = ServeDir::new(dist).fallback(ServeFile::new(dist.join("index.html")));

    Router::new()
        .nest("/api", api)
        .fallback_service(spa)
        .layer(SetResponseHeaderLayer::if_not_present(
            header::CACHE_CONTROL,
            HeaderValue::from_static("no-cache"),
        ))
}
```

Checked behavior: `/` and `/users/42` return `index.html`, `/api/health`
returns JSON, `/api/nope` returns 404, `.wasm` is served as
`application/wasm`, and a revalidation with `If-None-Match` returns 304.

- **Give `/api` its own 404 fallback.** Without it, the SPA fallback answers
  `/api/typo` with `index.html` and a 200, and the client tries to parse HTML
  as JSON.
- **Set `Cache-Control` on `index.html`.** `ServeDir` sends `ETag` and
  `Last-Modified` but no `Cache-Control`. Browsers then cache heuristically
  and can keep loading an old `index.html`, which points at old hashed files,
  after a deploy.
- Take the `dist` path from a flag or env var (clap `env`), not a hard-coded
  relative path, so the container and the dev checkout can differ.

In the container image, build `dist/` in a builder stage
(`trunk build --release --locked`) and copy it next to the binary. See the
`k8s-deployment` skill for the image and manifests.

### From any static host

Anything that serves files works, given three settings:

- **SPA fallback**: unknown paths serve `index.html` (if the app routes on the
  client).
- **`application/wasm`** as the `.wasm` content type. Trunk's dev server and
  Python's `http.server` send it (checked); check yours with `curl -sI`.
- **`Cache-Control: no-cache` on `index.html`.** The hashed `.js` and `.wasm`
  files can be cached forever. Files copied with `rel="copy-file"` or
  `rel="copy-dir"` are **not** hashed, so don't mark them immutable.

Let the server or CDN compress (brotli or gzip). Trunk's own
`data-compression-algorithm` is for hosts that can't.

## Review checklist

- [ ] Is Trunk pinned as `"github:trunk-rs/trunk"` in mise, not `trunk`?
- [ ] Does `index.html` have an explicit `<link data-trunk rel="rust" .../>`?
- [ ] Is `strip = true` absent from `[profile.release]`?
- [ ] Does `Trunk.toml` ignore `logs/**` (with the `/**`)?
- [ ] Are sibling crates listed in `[watch] watch`?
- [ ] Does CI run `trunk build --release --locked`?
- [ ] Is the app served from `/`, or built with a matching `--public-url`?
- [ ] Does `/api` have its own 404, and does `index.html` get `no-cache`?

## Further reading

- [The Trunk guide](https://trunk-rs.github.io/trunk/guide): asset types,
  hooks, the initializer (a loading progress bar), the
  `TrunkApplicationStarted` event, and the full configuration schema.
- [Trunk examples](https://github.com/trunk-rs/trunk/tree/main/examples):
  vanilla, Leptos, Yew, Tailwind, web workers, a backend proxy.
