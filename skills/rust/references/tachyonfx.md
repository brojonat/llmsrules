# Effects and animation with tachyonfx

[tachyonfx](https://github.com/ratatui/tachyonfx) (by junkdog, now under the
Ratatui org) adds shader-like effects to Ratatui apps: fades, dissolves,
sweeps, glitches. Orhun uses it in talks and apps for the "make the terminal
look modern" part of Ratatui's pitch. The app shape it plugs into is in
[`tui.md`](tui.md).

Checked with tachyonfx 0.25.2, ratatui 0.30.2 and Rust 1.99.1, in a
truecolor tmux session. tachyonfx 0.x minor releases break the API
regularly: pin `tachyonfx = "0.25"` and read the CHANGELOG before bumping.
tachyonfx 0.23+ depends on `ratatui-core`, which is what makes it share
`Buffer` and `Color` with ratatui 0.30; 0.21 and older can't be mixed with
ratatui 0.30.

```toml
# std only; the default features add the effect DSL (and its parser dependency)
tachyonfx = { version = "0.25.2", default-features = false, features = ["std"] }
```

## The model

**Effects post-process the frame.** Render widgets as usual, then let effects
change the cells already in the buffer (colors, symbols, positions), inside
the same `terminal.draw` closure. Ratatui then diffs and writes the result.
An effect is a stateful object: create it once, process it every frame until
it's done.

**Effects don't persist.** When an effect finishes and is dropped, the next
frame shows your widgets untouched again. To keep an end state, wrap it in
`fx::never_complete(..)` (or `prolong_end`), or change app state when it ends.

## Wiring it into the loop

The loop from [`tui.md`](tui.md), with effects. The `EffectManager` lives in
the app state, next to the table selection:

```rust
/// One key per animated UI slot: a new effect under a key replaces the old one.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum FxKey {
    #[default] // EffectManager::default() requires K: Default
    Updated,
}

// in App: pub effects: EffectManager<FxKey>,
```

```rust
const FRAME: Duration = Duration::from_millis(16); // ~60 fps while animating
let mut last_frame = Instant::now();
while app.running {
    // Real time since the last frame, capped: after blocking while idle, an
    // uncapped delta would finish a newly added effect in one frame.
    let elapsed = last_frame.elapsed().min(Duration::from_millis(100));
    last_frame = Instant::now();
    terminal.draw(|frame| {
        ui::render(app, theme, frame); // widgets first ...
        let area = frame.area();
        app.effects.process_effects(elapsed.into(), frame.buffer_mut(), area); // ... then effects
    })?;
    // Redraw every frame while something animates; otherwise sleep until an event.
    let event = if app.effects.is_running() {
        match events.recv_timeout(FRAME) {
            Ok(event) => event,
            Err(RecvTimeoutError::Timeout) => continue,
            Err(RecvTimeoutError::Disconnected) => anyhow::bail!("event channel closed"),
        }
    } else {
        events.recv()?
    };
    // ... handle event as before ...
}
```

Checked live: the startup fade and the update pulse animate at ~60 fps, then
the loop goes back to blocking (0 CPU ticks over 3 seconds idle).

- **Feed real elapsed time.** `tachyonfx::Duration` is its own millisecond
  type; `std::time::Duration` converts with `.into()` (sub-millisecond time
  is dropped, so animations run ~4% slow at 60 fps; harmless).
- **Effects advance only when you process them.** Keep drawing every ~16 ms
  while `is_running()` is true, or they freeze. chess-tui uses the same
  fast-while-animating, block-otherwise switch.
- **Cap the delta** (or reset `last_frame` when leaving idle): an hour-long
  delta finishes every effect instantly. glim uses exactly that as its
  "animations off" switch.

Adding effects from event handlers:

```rust
// Startup (main.rs): fade everything in from black.
app.effects.add_effect(
    fx::fade_from_fg(Color::Black, (600, Interpolation::QuadOut)).with_color_space(ColorSpace::Rgb),
);

// When new data arrives (app.rs): pulse the table body, not its border.
let pulse = fx::fade_from_fg(Color::Yellow, (400, Interpolation::QuadOut))
    .with_filter(CellFilter::Inner(Margin::new(1, 1)));
self.effects.add_unique_effect(FxKey::Updated, pulse);
```

`add_unique_effect` replaces whatever is running under that key, so ten
updates in a row restart one pulse instead of stacking ten. Cancel with
`cancel_unique_effect(key)`. Plain `add_effect` effects can't be cancelled,
so anything long-lived or endless goes under a key.

## Building effects

Timers are `ms` or `(ms, Interpolation)`: `fx::dissolve((300, Interpolation::QuadIn))`.

| Kind | Effects |
|---|---|
| Color | `fade_from(fg, bg, t)`, `fade_to`, `fade_from_fg`, `fade_to_fg`, `paint`, `hsl_shift`, `saturate`, `lighten`, `darken` |
| Text | `dissolve`, `coalesce` (dissolve in reverse), `evolve`, `explode` |
| Motion | `sweep_in`/`sweep_out(Motion, gradient, randomness, color, t)`, `slide_in`/`slide_out`, `expand`, `stretch`, `translate` |
| Endless | `Glitch::builder().action_ms(200..400).action_start_delay_ms(0..1).cell_glitch_ratio(1.0).build().into_effect()` (all three fields required; `use tachyonfx::IntoEffect`; never finishes on its own) |
| Custom | `fx::effect_fn(state, t, \|state, ctx, cells\| ...)`, or implement `Shader` |

| Combinator | Meaning |
|---|---|
| `fx::sequence(&[a, b])` | one after another |
| `fx::parallel(&[a, b])` | together; **later effects draw over earlier ones** |
| `fx::prolong_start(d, fx)` | hold the first frame (content stays hidden) for `d` |
| `fx::delay(d, fx)` | wait `d` first, **showing untouched content meanwhile** |
| `fx::prolong_end(d, fx)`, `fx::never_complete(fx)` | hold the end state |
| `fx::repeat(fx, RepeatMode::Times(n))`, `fx::repeating(fx)`, `fx::ping_pong(fx)` | loops |
| `fx::dispatch_event(sender, ev)` | send an app event when reached in a sequence |
| `fx::consume_tick()` | one-frame no-op: the "cancel" and "wait" primitive |

Modifiers on any effect: `.with_area(rect)`,
`.with_filter(CellFilter::Inner(Margin::new(1, 1)))` (inside a border) or
`Outer(..)` (the border ring), `Text`, `FgColor(c)`, `AllOf(vec![..])`;
`.with_pattern(RadialPattern::center())` for spatial progression;
`.with_color_space(ColorSpace::Rgb)`; `.reversed()`.

**Patterns from exabind**, junkdog's showcase app (KDE shortcuts on an
animated keyboard):

- **Effect recipes are plain functions** returning `Effect`, parameterized
  by `Rect` and `Color`: `open_category(bg, area)`, `starting_up()`.
- **One unique key per UI slot** (`SelectedCategory`, `KeyCapOutline`):
  selecting something new replaces the old animation.
- **Staggered reveals**: `prolong_start(random_delay, open(...))` per widget
  inside `parallel`, then `sleep(500)`, then `dispatch_event(..)` to tell the
  app the intro finished.
- **Border and content animate differently** in one composite: a `sweep_in`
  filtered to `Inner`, a `coalesce` filtered to `Outer`, with the effect that
  must win listed last.
- **The reducer that changes state also starts the effect**, in the same
  match arm, so state and animation can't drift apart.

**Moving areas.** An effect keeps the `Rect` it was given. For popups and
panes that move or resize, share a `RefRect` that the widget updates in
`render`, and wrap the effect in `fx::dynamic_area(rect, fx)` (glim's
popups).

**Designing effects visually**: [TachyonFX FTL](https://junkdog.github.io/tachyonfx-ftl/)
is a browser editor for the effect DSL (`EffectDsl::new().compiler().compile("fx::dissolve(500)")`,
default `dsl` feature). Design there, then paste the expression into Rust.

## Gotchas

1. **Process effects after rendering**, in the same `draw` closure. Before
   rendering, the widgets overwrite them.
2. **Truecolor only.** Interpolation always produces 24-bit RGB; 256-color
   terminals band or show wrong colors.
3. **Give widgets explicit colors.** `Color::Reset` is interpolated as white
   text on black, so fades on a themed terminal jump at the end.
4. **Fade in RGB.** The default HSL interpolation takes the shortest way
   around the hue wheel: fading dark gray to orange passed through green in
   testing. `.with_color_space(ColorSpace::Rgb)` fixes it.
5. **`Glitch` and `never_complete` never finish.** Give them a unique key or
   `fx::with_duration(..)`, or they stay in the manager forever.
6. **`with_filter` doesn't override a filter a child already has.** Put
   filters on the innermost effect when children need different ones.
7. **Argument order differs**: `frame.render_effect(&mut fx, area, dt)` but
   `fx.process(dt, buf, area)`. `hsl_shift(None, None, ..)` panics.
8. **Custom shaders without a timer must implement `reset`**: the default
   panics, which breaks `repeat` and `ping_pong`.
9. **`sendable` feature** if effects or the manager cross threads (stored in
   state that moves into a tokio task).

## In the browser

The same effects run in a web page through Ratzilla (Ratatui for the DOM,
canvas or WebGL2): `tachyonfx = { version = "0.25", default-features = false, features = ["wasm"] }`,
`web_time::Instant` instead of `std::time::Instant`, and Trunk to build.
exabind ships a native and a web binary over one core crate this way. See
[`ratzilla.md`](ratzilla.md) (a checked example with a fade on the canvas
backend), [`wasm.md`](wasm.md) and [`trunk.md`](trunk.md).

## Review checklist

- [ ] Are effects processed after widgets, in the same `draw` closure?
- [ ] Is the elapsed time real, and capped or reset after idling?
- [ ] Does the loop redraw every ~16 ms while `is_running()`, and block otherwise?
- [ ] Is every long-lived or endless effect under a unique key?
- [ ] Do animated widgets have explicit fg/bg colors, and do fades use RGB?
- [ ] Is tachyonfx pinned to a minor version that matches the ratatui release?

## Further reading

- [tachyonfx](https://github.com/ratatui/tachyonfx): README, `examples/`
  (`effect-showcase`, `effect-registry`), and the CHANGELOG's breaking-change
  notes.
- [exabind](https://github.com/junkdog/exabind): `core/src/fx/effect.rs` for
  effect recipes, `core/src/app.rs` for the reducer.
- [glim](https://github.com/junkdog/glim): `src/effect_registry.rs`, the
  wrapper junkdog recommends around `EffectManager`.
- Orhun Parmaksız, [Bringing Terminal Aesthetics to the Web](https://www.youtube.com/watch?v=iepbyYrF_YQ)
  (FOSDEM 2025): tachyonfx and the Buffer concept it builds on.
