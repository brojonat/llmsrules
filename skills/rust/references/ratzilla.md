# Terminal UIs in the browser with Ratzilla

[Ratzilla](https://github.com/ratatui/ratzilla) runs Ratatui in a web page:
the same widgets, layouts and render code, drawn into the DOM, a canvas, or
WebGL2 instead of a terminal. Orhun Parmaksız built it (FOSDEM 2025) so a
terminal app could move to the web by swapping the backend, with no
JavaScript and no npm. Sites built with it include
[terminalcollective.org](https://terminalcollective.org),
[TachyonFX FTL](https://junkdog.github.io/tachyonfx-ftl/) and
[exabind](https://junkdog.github.io/exabind).

This builds on three other docs: [`tui.md`](tui.md) for the Ratatui app
shape, [`wasm.md`](wasm.md) for what Rust can't do in a browser, and
[`trunk.md`](trunk.md) for building and deploying.

Checked with ratzilla 0.3.1, ratatui 0.30.2, tachyonfx 0.25.2, Trunk 0.22.1
and Rust 1.99.1: one shared core crate, run as a native TUI in tmux and as a
web page in headless Chromium, which drew the identical screen. Several
problems below are 0.3.1 bugs that the template doesn't hit until you add a
layout or a full-screen widget.

## One core, two frontends

The point of Ratzilla is "write Rust once, run everywhere": keep the app
in a crate that only builds frames, and give it a thin frontend per target.

```
Cargo.toml       [workspace] members = ["core", "tui", "web"]
core/            App, Command, render(): ratatui only, no backend
tui/             crossterm frontend: ratatui::run + event::read
web/             Ratzilla frontend: draw_web + on_key_event, index.html
```

```toml
# Cargo.toml (workspace)
[workspace.dependencies]
# std is required: without it, any Layout fails to link on wasm (below).
ratatui = { version = "0.30.2", default-features = false, features = ["std"] }

# core/Cargo.toml
[dependencies]
ratatui = { workspace = true }                           # no backend

# tui/Cargo.toml
[dependencies]
counter-core = { path = "../core" }
ratatui = { workspace = true, features = ["crossterm"] }

# web/Cargo.toml
[dependencies]
counter-core = { path = "../core" }
console_error_panic_hook = "0.1"
ratzilla = "0.3.1"
tachyonfx = { version = "0.25.2", default-features = false, features = ["wasm"] }
web-time = "1"
```

The core owns state, the `Command` enum and rendering, as in
[`tui.md`](tui.md#app-shape):

```rust
/// Frontends translate their own key events into these.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Command { Increment, Decrement, Quit, Nothing }

impl App {
    pub fn run_command(&mut self, cmd: Command) { /* change state */ }

    pub fn render(&self, frame: &mut Frame) {
        let area = frame.area().centered(Constraint::Length(30), Constraint::Length(5));
        // ... Block + Paragraph ...
    }
}
```

Each frontend maps its own key type to `Command`, because crossterm's and
Ratzilla's `KeyEvent`s are different types (and the orphan rule keeps the
mapping out of the core):

```rust
// tui/src/main.rs
fn command(key: KeyEvent) -> Command {
    match (key.modifiers, key.code) {
        (KeyModifiers::CONTROL, KeyCode::Char('c')) | (_, KeyCode::Char('q')) => Command::Quit,
        (_, KeyCode::Right) => Command::Increment,
        (_, KeyCode::Left) => Command::Decrement,
        _ => Command::Nothing,
    }
}
```

Checked: after → → ← both frontends draw exactly this:

```
╭ counter ───────────────────╮
│                            │
│          Count: 1          │
│                            │
╰──────── ←/→ change ────────╯
```

Trunk builds only the web package (`trunk build` inside `web/`), so
crossterm never reaches the wasm build. Don't run
`cargo build --workspace --target wasm32-unknown-unknown`: that pulls the
crossterm frontend into the wasm build too.

## The web frontend

```rust
use std::{cell::RefCell, io, rc::Rc};

use counter_core::{App, Command};
use ratzilla::{
    CanvasBackend, WebRenderer,
    event::{KeyCode, KeyEvent},
    ratatui::{Terminal, style::Color},
    web_sys::{HtmlElement, wasm_bindgen::JsCast},
};
use tachyonfx::{ColorSpace, EffectManager, Interpolation, fx};
use web_time::Instant; // std::time::Instant panics in the browser

fn command(key: KeyEvent) -> Command {
    match key.code {
        KeyCode::Right => Command::Increment,
        KeyCode::Left => Command::Decrement,
        _ => Command::Nothing, // no Quit: a web page doesn't exit
    }
}

/// Ratzilla listens for keys on the terminal element, not the page, so keys do
/// nothing until it has focus. Returns false until the element exists.
fn focus_terminal() -> bool {
    let element = ratzilla::web_sys::window()
        .and_then(|w| w.document())
        .and_then(|d| d.query_selector("[tabindex]").ok().flatten())
        .and_then(|e| e.dyn_into::<HtmlElement>().ok());
    element.is_some_and(|e| e.focus().is_ok())
}

fn main() -> io::Result<()> {
    console_error_panic_hook::set_once();
    let app = Rc::new(RefCell::new(App::default()));
    let mut terminal = Terminal::new(CanvasBackend::new()?)?;

    let keys = Rc::clone(&app);
    terminal.on_key_event(move |key| keys.borrow_mut().run_command(command(key)))?;

    let mut effects: EffectManager<()> = EffectManager::default();
    effects.add_effect(
        fx::fade_from_fg(Color::Black, (800, Interpolation::QuadOut)).with_color_space(ColorSpace::Rgb),
    );
    let mut last_frame = Instant::now();

    // Called on every requestAnimationFrame: the browser is the loop.
    let mut focused = false;
    terminal.draw_web(move |frame| {
        // The terminal element is only added to the page by the first draw.
        if !focused {
            focused = focus_terminal();
        }
        let elapsed = last_frame.elapsed();
        last_frame = Instant::now();
        app.borrow().render(frame); // widgets first ...
        let area = frame.area();
        effects.process_effects(elapsed.into(), frame.buffer_mut(), area); // ... then effects
    });
    Ok(())
}
```

```html
<!-- web/index.html -->
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>counter</title>
    <link data-trunk rel="rust" data-wasm-opt="z" />
    <style>
      body { margin: 0; height: 100vh; background: #121212; }
      pre { font-family: monospace; font-size: 16px; margin: 0; }
    </style>
  </head>
  <body></body>
</html>
```

How it differs from the terminal loop:

- **There is no loop to write.** `draw_web` hands your closure to
  `requestAnimationFrame` and calls it every frame (about 60 per second)
  for as long as the page is open; browsers pause it in background tabs.
  Ratatui's diff keeps unchanged cells from being redrawn, but your render
  code still runs each frame, so keep it cheap.
- **Events are callbacks**, not a channel: `on_key_event` and
  `on_mouse_event` (mouse positions arrive as grid `col`/`row`). State shared
  between the callbacks and the draw closure is `Rc<RefCell<App>>`: one
  thread, no `Arc<Mutex>`.
- **No quitting, no signals, no raw mode, no panic hook to restore a
  terminal.** `console_error_panic_hook` is the only setup, and a panic ends
  the app until reload.
- **Effects work unchanged**, with tachyonfx's `wasm` feature and
  `web_time::Instant` (checked: the fade runs from dim to full color in the
  browser).

## Choosing a backend

Measured on the counter above (release build, `data-wasm-opt="z"`):

| | DomBackend | CanvasBackend | WebGl2Backend |
|---|---|---|---|
| `.wasm` size | 316 KB (122 KB gzipped) | 284 KB (110 KB gzipped) | 1.5 MB (1.1 MB gzipped) |
| Renders as | `<span>` per cell | canvas, browser fonts | GPU, font atlas |
| Hyperlinks, text selection | selection | neither | both |
| 60 fps full screen | no | no | yes |
| Problems in 0.3.1 | crashes at some window sizes (below) | emoji wider than one cell | default font atlas drops glyphs (below) |

- **Default to `CanvasBackend`**: the smallest bundle, correct box drawing and
  arrows, and none of the 0.3.1 bugs below.
- **Use `WebGl2Backend`** for full-screen animation, hyperlinks or text
  selection, and accept the extra megabyte. Configure the dynamic font atlas:
  ```rust
  // The default static atlas silently drops glyphs it doesn't contain.
  let options = WebGl2BackendOptions::new()
      .font_atlas_config(FontAtlasConfig::dynamic(&["monospace"], 16.0));
  let mut terminal = Terminal::new(WebGl2Backend::new_with_options(options)?)?;
  ```
  With the default atlas, `←/→ change` rendered as `  /  change` and
  rounded corners turned square.
- **Use `DomBackend`** when you need CSS styling or accessibility, after
  0.3.1's sizing bug is fixed in a release.

## Gotchas (0.3.1)

1. **Any `Layout` fails to link without ratatui's `std` feature.** Ratzilla
   turns on ratatui's `layout-cache`, which needs a `critical-section`
   implementation that nothing provides on wasm:
   `undefined symbol: _critical_section_1_0_acquire`. The official template
   (`ratatui = { default-features = false }`) builds only because its
   example never splits a layout; one `Layout::vertical(...)` breaks it.
   Fix: `features = ["std"]` on ratatui (browser wasm has std). Ratzilla's
   own examples add `critical-section = { version = "1.2", features = ["std"] }`
   instead, which also works.
2. **Keys go nowhere until the terminal is focused.** Key listeners are on
   the terminal element, not the page, and nothing focuses it, so arrow keys
   do nothing until the user clicks. The element is only attached by the
   first draw, so focusing it right after creating the terminal fails;
   `focus_terminal()` above retries from inside `draw_web` until it works.
3. **`DomBackend` crashes when something draws into the bottom-right
   edge.** It reports a terminal size from the window but builds its grid
   from measured font metrics; when they disagree, writing the last cells
   panics with `index out of bounds: the len is 4522 but the index is 4522`
   (`dom.rs:321`). A full-screen `Block::bordered()` crashed at 1280x720 and
   1000x700 but not at 800x400, so it may not show on the developer's screen.
   A full-screen tachyonfx fade triggers it the same way. Fixed on `main`
   (`size()` now returns the grid size), not yet released. Canvas and WebGL2
   were fine at the same sizes.
4. **The template's `index.html` has no `<link data-trunk rel="rust"/>`**,
   so release builds skip wasm-opt ([`trunk.md`](trunk.md#always-write-the-relrust-link)).
   It also ignores `on_key_event`'s `Result` (a compiler warning) and depends
   on color-eyre without using it.
5. **The `std` gaps from [`wasm.md`](wasm.md) apply**: `std::time::Instant`
   panics (use `web_time`), `println!` disappears, threads don't exist.

## Testing

- **Keep logic in the core and test it natively**: `cargo test -p counter-core`,
  plus the `TestBackend` snapshots from [`tui.md`](tui.md#testing). They cover
  the web build too, since the core draws the same frames.
- **Lint the web crate for wasm**: `cargo clippy --target wasm32-unknown-unknown`
  inside `web/`.
- **Drive the page with Playwright.** With `DomBackend`, read the screen as
  text (`document.body.innerText`); with Canvas and WebGL2, take screenshots.
  Use full headless Chromium (`chromium.launch({ channel: 'chromium' })`):
  Playwright's default headless shell rendered WebGL2's dynamic atlas
  clipped and borderless, while full headless Chromium rendered it correctly.
  Fail the test on any `console.error` (panics land there) and on
  `pageerror`.
- **Test more than one window size.** The DomBackend crash depended on the
  viewport.

## Review checklist

- [ ] Is the app in a backend-free core crate, with ratatui's `std` feature?
- [ ] Does each frontend map its own key events to the core's `Command`?
- [ ] Is the terminal element focused on load?
- [ ] Canvas by default; WebGL2 only with the dynamic font atlas; DOM only
      once the sizing fix is released?
- [ ] Does `index.html` have the `rel="rust"` link?
- [ ] Is time from `web_time`, and is `console_error_panic_hook` installed?
- [ ] Was the page checked in a browser at more than one window size?

## Further reading

- [Ratzilla](https://github.com/ratatui/ratzilla): `examples/` (demo, pong,
  animations, website) and the [backend comparison](https://docs.rs/ratzilla/latest/ratzilla/backend/index.html).
- Orhun Parmaksız, [Bringing Terminal Aesthetics to the Web With Rust (and Vice Versa)](https://www.youtube.com/watch?v=iepbyYrF_YQ)
  (FOSDEM 2025): why Ratzilla exists and how it differs from earlier attempts.
- [exabind](https://github.com/junkdog/exabind): one core crate, a native
  binary and a WebGL2 web binary, with tachyonfx effects in both.
