# Rust in the browser (wasm32)

What changes when Rust runs in a web page instead of on a server. For
building, serving and deploying the result, see [`trunk.md`](trunk.md).

## When it earns its place

The default for a web UI is still plain HTML with a sprinkle of Datastar,
driven by the server. Rust compiled to WebAssembly is a second runtime to ship
and debug, so it needs a reason:

- **One codebase, two targets.** Ratzilla (Orhun Parmaksız, FOSDEM 2025) runs
  Ratatui terminal apps in the browser by swapping the backend: the widgets,
  the draw loop and the event handling stay the same, and the backend renders
  cells as DOM `<span>`s or onto a canvas (see [`ratzilla.md`](ratzilla.md)).
  The same goes for domain logic: the
  serde types, validation and parsers your axum service uses can run
  client-side unchanged.
- **No JavaScript toolchain.** No npm, no bundler config, no `package.json`.
  A Trunk app is `fn main`, an `index.html`, and `trunk serve`. Event handlers
  are Rust closures registered through `web-sys`.
- **Compute in the client.** Parsing, simulation, image and audio processing,
  and canvas rendering at 60 fps run at near-native speed, offline, without a
  round trip.
- **Rust's types and crates come along**, apart from the `std` gaps below.

The costs:

- **Download size.** A hello world is 292 KB unoptimized and 22-25 KB
  optimized (11 KB gzipped). UI frameworks add much more. Nothing renders
  until the wasm is fetched and compiled.
- **Every DOM call crosses into JavaScript.** A UI that mostly shuffles DOM
  nodes isn't faster in Rust; the win is in computing, not in DOM updates.
- **`std` partly doesn't work**, and some failures only show up at runtime.
- **Another target to keep compiling**: lint and check it in CI.

Pick it when the client has to compute, render continuously, work offline, or
reuse Rust code you already have. For CRUD pages and dashboards, stay with
server-rendered HTML.

**Keep the layers thin.** The Ratzilla talk's main argument: earlier attempts
to put Ratatui on the web worked but stacked frameworks (egui plus Bevy, or a
Yew app with a manual hydration step), so a simple app required learning three
systems. Start with plain `web-sys`, or a library that does one thing. Reach
for a component framework (Leptos, Yew, Dioxus) only when you are really
building a component-tree app.

## Target and toolchain

The browser target is `wasm32-unknown-unknown`: no OS, no libc. Pin it next to
the channel in `rust-toolchain.toml`, and rustup installs it on the first
`cargo` call (checked: removing the target and running `cargo build` put it
back):

```toml
[toolchain]
channel = "stable"
components = ["clippy", "rustfmt", "rust-analyzer"]
targets = ["wasm32-unknown-unknown"]
```

A distro's packaged Rust without rustup (Arch's `rust`, for example) ships
only the host target, and the build fails with
`can't find crate for std ... the wasm32-unknown-unknown target may not be installed`.
Install rustup (or the distro's `rust-wasm` package on Arch).

## `std` on wasm32-unknown-unknown

All of these were checked in headless Chromium:

| Call | What happens | Use instead |
|---|---|---|
| `std::time::Instant::now()` | compiles, **panics at runtime** | `web_time::Instant` (drop-in) |
| `std::time::SystemTime::now()` | compiles, **panics at runtime** | `web_time::SystemTime` |
| `std::thread::spawn` | `Builder::spawn` returns `Unsupported`; `spawn` panics | `spawn_local`, or a Web Worker |
| `println!`, `eprintln!` | **silently discarded** | `web_sys::console::log_1`, or `tracing-wasm` |
| `std::fs`, `std::net`, `std::process` | unsupported | `fetch` (`gloo-net`), `localStorage`, ... |
| `getrandom` (via `rand`, `uuid`, ...) | **compile error** | enable its `wasm_js` feature (below) |

The time panics are the dangerous ones: the code compiles, and it panics when
a user clicks the button that measures something. `web-time` re-exports
`std::time` on native targets, so use it everywhere in code that may run in
the browser.

**Randomness.** `getrandom` refuses to guess a randomness source on
`wasm32-unknown-unknown`. Enable the browser backend for the wasm target only:

```toml
[target.'cfg(all(target_arch = "wasm32", target_os = "unknown"))'.dependencies]
getrandom = { version = "0.4", features = ["wasm_js"] }
```

Checked with `rand` 0.10 (getrandom 0.4.3) and with getrandom 0.3.4: the
feature alone is enough, no `RUSTFLAGS` needed. Cargo enables a feature per
major version, so if `cargo tree --target wasm32-unknown-unknown -i getrandom`
shows two versions, add a line for each. `uuid` has its own switch:
`features = ["v4", "js"]`.

## Panics

Install the panic hook as the first line of `main`:

```rust
fn main() {
    console_error_panic_hook::set_once();
    // ...
}
```

Without it, a panic shows up in the console as `RuntimeError: unreachable`
and nothing else. With it, you get `panicked at src/main.rs:12:9` and the
message. Either way the instance is dead after a panic: there is no unwinding
to catch, and the page needs a reload.

## Async and the event loop

There's no Tokio runtime. The browser's event loop polls your futures, and
`wasm_bindgen_futures::spawn_local` takes the place of `tokio::spawn`. It
returns nothing (no `JoinHandle`), and the task starts after the current code
yields: a task spawned in `main` runs after `main` returns (checked).

Everything in [`cancellation.md`](cancellation.md) still applies: a future
dropped mid-`.await` stops there. The mutex trap has a single-threaded twin:
state is `Rc<RefCell<_>>` (not `Arc<Mutex<_>>`), and a `borrow_mut()` held
across an `.await` panics when another task borrows the same cell.

**There is no `sleep`, and blocking freezes the tab.** A render loop is a
closure that re-schedules itself with `requestAnimationFrame`. Checked: this
ran at 60 frames per second, with key presses handled in Rust:

```rust
use std::{cell::RefCell, rc::Rc};

use wasm_bindgen::{JsCast, prelude::Closure};
use web_sys::{KeyboardEvent, window};

/// Calls `frame` once per display refresh, forever. The closure re-schedules
/// itself, so it has to own a handle to itself: hence Rc<RefCell<Option<_>>>.
fn animation_loop(mut frame: impl FnMut(f64) + 'static) {
    let cb: Rc<RefCell<Option<Closure<dyn FnMut(f64)>>>> = Rc::new(RefCell::new(None));
    let next = cb.clone();
    *cb.borrow_mut() = Some(Closure::new(move |ts: f64| {
        frame(ts);
        request_frame(next.borrow().as_ref().expect("set before first frame"));
    }));
    request_frame(cb.borrow().as_ref().expect("just set"));
}

fn request_frame(cb: &Closure<dyn FnMut(f64)>) {
    window()
        .expect("no window")
        .request_animation_frame(cb.as_ref().unchecked_ref())
        .expect("requestAnimationFrame");
}

fn main() {
    console_error_panic_hook::set_once();
    let doc = window().and_then(|w| w.document()).expect("no document");
    let body = doc.body().expect("no body");

    // Shared by the frame loop and the key handler. One thread: Rc<RefCell>.
    let state = Rc::new(RefCell::new((0u64, String::new()))); // (frames, last key)

    let s = state.clone();
    let on_key = Closure::<dyn FnMut(KeyboardEvent)>::new(move |e: KeyboardEvent| {
        s.borrow_mut().1 = e.key();
    });
    doc.add_event_listener_with_callback("keydown", on_key.as_ref().unchecked_ref())
        .expect("addEventListener");
    on_key.forget(); // the listener lives as long as the page; leak it on purpose

    animation_loop(move |_ts| {
        let mut st = state.borrow_mut();
        st.0 += 1;
        body.set_inner_text(&format!("frames={} key={}", st.0, st.1));
    });
}
```

A `Closure` handed to JavaScript must outlive every call. Dropping it while
the browser still holds the callback makes the next call throw `closure
invoked recursively or after being dropped` (checked). For page-long
listeners, `.forget()` is right. For temporary ones, keep the `Closure` in a
struct and remove the listener before dropping it.

## Testing

- **Keep logic in plain modules** with no `web-sys` in their signatures, and
  test them natively with `cargo test`. That works even when the crate
  depends on `web-sys` (checked), since the bindings compile on every target.
- **Lint the wasm target too**: `cargo clippy --target wasm32-unknown-unknown`
  catches `#[cfg(target_arch = "wasm32")]` code that a native build never
  compiles.
- Tests that need real browser APIs: `wasm-bindgen-test` with a headless
  browser. Smoke-test the built page with Playwright: load it, fail on any
  `pageerror`, and assert on what rendered.

## Review checklist

- [ ] Does the client really need to compute, render continuously, or reuse
      Rust code, or would server-rendered HTML do?
- [ ] Is `console_error_panic_hook::set_once()` the first line of `main`?
- [ ] Any `std::time`, `std::thread`, `println!` or `std::fs` in code that runs
      in the browser?
- [ ] Is getrandom's `wasm_js` feature enabled for every getrandom version
      in the wasm dependency tree?
- [ ] Is any `RefCell` borrow held across an `.await`?
- [ ] Does every `Closure` passed to JavaScript outlive its last call?
- [ ] Does CI run `cargo clippy --target wasm32-unknown-unknown`?

## Further reading

- Orhun Parmaksız, "Bringing Terminal Aesthetics to the Web With Rust (and
  Vice Versa)", FOSDEM 2025:
  [video](https://www.youtube.com/watch?v=iepbyYrF_YQ). Introduces Ratzilla
  ([`ratatui/ratzilla`](https://github.com/ratatui/ratzilla)). The source of the
  "keep the layers thin" argument and the `requestAnimationFrame` loop.
- [wasm-bindgen guide](https://wasm-bindgen.github.io/wasm-bindgen/):
  closures, JS interop, `web-sys` feature flags.
- [getrandom WebAssembly support](https://docs.rs/getrandom/latest/getrandom/#webassembly-support).
