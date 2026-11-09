# Terminal UIs with Ratatui

Interactive terminal apps the way Orhun Parmaksız (Ratatui's lead
maintainer) builds them: binsider, flawz, kmon, systeroid, tuitar. The
non-interactive side (args, JSON output, exit codes) is in [`cli.md`](cli.md),
animations in [`tachyonfx.md`](tachyonfx.md), and slides in
[`presenterm.md`](presenterm.md).

Code here comes from a reference app (`dirsize`) checked with ratatui 0.30.2,
tachyonfx 0.25.2, insta 1.49 and Rust 1.99.1: clippy clean, tests passing,
and driven live in tmux.

## The model: immediate mode

> "You have a rendering loop, you have a state that you use in this
> rendering loop, and you basically redraw everything in this loop based on
> the state." (Orhun, Code to the Moon, 2026)

Every frame renders the whole UI from state; Ratatui diffs the result and
writes only the cells that changed. To hide a widget, don't render it. To
switch views, branch on a field. Nothing is retained between frames except
your state. Ratatui doesn't read input either: events come from crossterm
(or anything else), which is why the same widgets run on a microcontroller
display or in a browser ([`ratzilla.md`](ratzilla.md)).

## When to take over the terminal

- **Only when stdout is a terminal.** Otherwise print JSON lines and exit
  ([`cli.md`](cli.md#output-data-on-stdout-people-on-stderr)). A TUI drawn into
  `| grep` shows nothing and hangs waiting for keys.
- **Progress for a one-shot command** doesn't need the full screen:
  `ratatui::init_with_options(TerminalOptions { viewport: Viewport::Inline(8) })`
  draws in a few lines under the prompt, and `terminal.insert_before(...)`
  prints finished lines above it into normal scrollback. Enable ratatui's
  `scrolling-regions` feature to avoid flicker.
- **Pickers whose result goes to stdout** (fzf-style) must draw on stderr.
  `ratatui::init` always uses stdout, so build
  `Terminal::new(CrosstermBackend::new(BufWriter::new(stderr())))` yourself
  and install your own restoring panic hook. Buffer it: stderr is unbuffered.

## Terminal lifecycle

```rust
// main.rs, after parsing args and deciding a TUI is wanted
ratatui::run(|terminal| dirsize::run(terminal, &mut app, &Theme::default(), &rx))
```

`ratatui::run` (0.30) enters raw mode and the alternate screen, runs the
closure, and restores the terminal even if the closure returns an error.
`init`/`run` also install a panic hook that restores the terminal and then
calls the previous hook. The ladder when you need more control: `run` →
`init` + `restore` → `try_init` + `try_restore` → building `Terminal` by hand.

- **Install other panic hooks first** (`color_eyre::install()`,
  `better-panic`), then `init`, so the terminal is restored before the report
  prints.
- **`restore()` undoes only raw mode and the alternate screen.** Mouse
  capture, bracketed paste, focus reporting and keyboard-enhancement flags
  stay on and spray escape codes into the shell. Turn them off yourself, on
  exit and in a chained panic hook (flawz):

  ```rust
  let terminal = ratatui::try_init()?;
  execute!(stdout(), EnableMouseCapture)?;
  let hook = panic::take_hook();
  panic::set_hook(Box::new(move |info| {
      let _ = execute!(stdout(), DisableMouseCapture);
      hook(info);
  }));
  // on exit: execute!(stdout(), DisableMouseCapture)?; ratatui::try_restore()?;
  ```
- **Raw mode turns Ctrl-C into a key press.** No `SIGINT` arrives, so map
  `Ctrl+c` to quit yourself (below).
- **Import crossterm through `ratatui::crossterm`.** Two crossterm versions
  in one build means two event queues and raw mode that may never be
  restored; Orhun's newer apps have no direct crossterm dependency. Check
  with `cargo tree -i crossterm`.

## App shape

Ratatui doesn't impose an architecture, and its templates
(`cargo generate ratatui/templates`) offer several: `simple` (blocking
`event::read`), `event-driven` (a thread sends ticks and events over a
channel), async variants, and `component`. Orhun recommends `component` to
others for big apps, but every app of his uses the event-driven shape he
wrote in 2019, which became that template:

```
src/
  main.rs     args → JSON or TUI; spawns the input thread and background jobs
  lib.rs      pub fn run<B: Backend>(terminal, app, theme, events): the loop
  app.rs      App (all UI state) + Command enum + run_command
  event.rs    Event enum + input thread + background jobs
  ui.rs       render functions + Theme
```

**One state struct, one command enum.** Keys are translated in one place;
handlers never inspect raw key codes:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Command { Next, Previous, ToggleSort, Quit, Nothing }

impl From<KeyEvent> for Command {
    fn from(key: KeyEvent) -> Self {
        match (key.modifiers, key.code) {
            // Raw mode turns Ctrl-C into a key press, not SIGINT.
            (KeyModifiers::CONTROL, KeyCode::Char('c')) => Self::Quit,
            (_, KeyCode::Char('q') | KeyCode::Esc) => Self::Quit,
            (_, KeyCode::Char('j') | KeyCode::Down) => Self::Next,
            (_, KeyCode::Char('k') | KeyCode::Up) => Self::Previous,
            (_, KeyCode::Char('s')) => Self::ToggleSort,
            _ => Self::Nothing,
        }
    }
}
```

For modal UIs (a search box), pick the mapping by mode before converting:
binsider does `if state.input_mode { Command::Input(..) } else { Command::from(key) }`.

**One channel carries everything** the loop reacts to: keys, resizes, ticks,
and results from background work:

```rust
pub enum Event {
    Key(KeyEvent),
    Resize,
    Tick,
    Sized(PathBuf, u64), // a background job finished
}

/// Reads terminal input and emits ticks. Only `main` spawns this; tests send
/// events into the channel themselves.
pub fn spawn_input(tx: Sender<Event>, tick: Duration) {
    thread::spawn(move || {
        let mut last_tick = Instant::now();
        loop {
            let timeout = tick.saturating_sub(last_tick.elapsed());
            if event::poll(timeout).expect("poll terminal") {
                let ev = match event::read().expect("read terminal") {
                    event::Event::Key(k) if k.kind == KeyEventKind::Press => Event::Key(k),
                    event::Event::Resize(..) => Event::Resize,
                    _ => continue, // ignore the rest; never unimplemented!()
                };
                if tx.send(ev).is_err() {
                    return; // the app is gone
                }
            }
            if last_tick.elapsed() >= tick {
                last_tick = Instant::now();
                if tx.send(Event::Tick).is_err() {
                    return;
                }
            }
        }
    });
}
```

Slow work (scanning, searching, network) runs on its own thread and sends its
result as an `Event`, so the UI never blocks. flawz re-runs a search on every
keystroke this way.

**The loop is generic over the backend and takes the channel as a
parameter.** Explicit dependencies make the whole loop testable with no
terminal and no threads:

```rust
pub fn run<B: Backend>(
    terminal: &mut Terminal<B>,
    app: &mut App,
    theme: &Theme,
    events: &Receiver<Event>,
) -> anyhow::Result<()>
where
    B::Error: Send + Sync + 'static,
{
    while app.running {
        terminal.draw(|frame| ui::render(app, theme, frame))?;
        match events.recv()? {
            Event::Key(key) => app.run_command(Command::from(key)),
            Event::Sized(path, size) => app.sized(path, size),
            Event::Resize | Event::Tick => {} // redraw on the next iteration
        }
    }
    Ok(())
}
```

Blocking on `recv` idles at zero CPU (checked: 0 CPU ticks over 3 seconds).
Poll faster only while something animates; see [`tachyonfx.md`](tachyonfx.md).
Use tokio and crossterm's `EventStream` when the app does network I/O; Orhun:
"I don't usually need this when I don't make network requests."

Event-handling rules:

- **Filter `KeyEventKind::Press`.** Windows (and the kitty keyboard protocol)
  also send release events, so every key fires twice.
- **Ignore events you don't handle.** binsider and flawz have
  `_ => unimplemented!()` / `Paste(_) => unimplemented!()` in their event
  threads, which panics the moment bracketed paste or focus reporting is
  turned on. Don't copy it.
- **Resize just means "draw again".** `frame.area()` is re-read on every draw.
- **Running `$EDITOR` or a child process**: stop the input thread from
  reading, `restore()`, run it, `init()` again, then `terminal.clear()`.
  binsider pauses its event thread with an `AtomicBool` while it traces.

## Rendering

```rust
pub fn render(app: &mut App, theme: &Theme, frame: &mut Frame) {
    let hints = KEYS.iter().map(|(k, d)| format!(" {k} {d} ")).collect::<String>();
    let block = Block::bordered()
        .border_type(BorderType::Rounded)
        .border_style(theme.border)
        .title(Line::styled(" dirsize ", theme.title))
        .title_bottom(Line::styled(hints, theme.hint));
    // ... rows ...
    frame.render_stateful_widget(table.block(block), frame.area(), &mut app.table);
}
```

- **Render functions per region** (`render_header`, `render_list`, ...) or
  `impl Widget for &App`. Implement `Widget` for `&T` when rendering only
  reads; `StatefulWidget` when the widget's state (selection, scroll) lives
  outside it. A custom widget writes cells into the `Buffer`; compose by
  calling `.render()` on inner widgets.
- **Never fetch or compute inside `terminal.draw`.** Update state from
  events; drawing only reads it.
- **Draw the layout as ASCII in a doc comment** above `render`, then split
  with `let [header, body] = Layout::vertical([Length(1), Fill(1)]).areas(area);`
  (Orhun's workshop does both). Popups:
  `let popup = area.centered(Constraint::Percentage(60), Constraint::Length(10));`
  (0.30) then `frame.render_widget(Clear, popup)` before drawing into it. Try constraints in Ratatui's
  `constraint-explorer` example.
- **Cap what you render.** binsider renders at most 100 list rows and pages
  by index; tables of 100k rows shouldn't build 100k `Row`s per frame.
- **Measure text with `Line::width()`**, not `.len()`: wide characters take
  two cells. Clip hand-computed rects with `area.intersection(buf.area)`
  to avoid out-of-range panics.
- **One `terminal.draw` per frame.** Two draws overwrite each other.

### Making it look good

Ratatui's stated goals are ease of use and "aesthetically pleasing and
visually appealing" terminals (EuroRust 2024). What Orhun's apps do:

- **A `Theme` struct of semantic `Style`s** (`border`, `title`, `selected`,
  `hint`, ...) instead of colors scattered through render code. flawz ships
  Dracula, Nord, One Dark, Gruvbox and Catppuccin as a `ValueEnum` behind
  `--theme`, with a screenshot of each in the README.
- **Key hints always visible**, in the block's `title_bottom`, built from one
  `const KEYS: &[(&str, &str)]` table so help and bindings can't drift.
- **Vim keys plus arrows**: `j/k`, `h/l`, `Ctrl-d/u`, `/` to search, `q`/`Esc`
  to quit. "Everyone usually follows the same standard."
- **Borders are optional.** Asked why Ratatui apps box everything, Orhun said
  it's an accident of the examples using `Block`, not a recommendation. A
  background color or a dim separator often reads better.
- **Rounded borders and dim decorations** (`Color::Rgb(100,100,100)` titles
  like `|binsider-0.3.2|`), threshold colors (green/yellow/red), and a dimmed
  background behind popups.
- **Match the terminal's background.** binsider probes light or dark with
  `termbg` and picks its accent color (overridable by `--accent-color`).
- **Flair from tachyonfx** (effects drawn "one layer up" from your widgets)
  and `tui-big-text` for splash headers.

## Logging

Never write logs to stdout or stderr while the TUI owns the screen: it
corrupts the display. Log to a file with `tracing` (keep the
`tracing_appender` guard alive in `main`), using the house convention:
`logs/app.log`, followed with `tail -f`. For an in-app log pane, `tui-logger`
(systeroid toggles one with a key).

## Testing

Design for it, as Orhun says: "expose a render function that will take your
application state, or maybe take a backend."

**Commands without a terminal:**

```rust
#[test]
fn ctrl_c_quits() {
    let ctrl_c = KeyEvent::new(KeyCode::Char('c'), KeyModifiers::CONTROL);
    assert_eq!(Command::from(ctrl_c), Command::Quit);
}
```

**The whole loop, scripted, snapshotted.** Queue events into the channel
(including results that would come from background jobs, so the test is
deterministic), run the real loop on a `TestBackend`, and snapshot the screen
with `insta`. This is systeroid's integration test and kmon's approach:

```rust
#[test]
fn sizes_arrive_then_sort_then_quit() {
    let mut app = App::new(vec!["a".into(), "b".into(), "c".into()]);
    let (tx, rx) = mpsc::channel();
    for ev in [
        Event::Sized(PathBuf::from("b"), 3 * 1024 * 1024),
        Event::Sized(PathBuf::from("a"), 512),
        key('s'),
        key('j'),
        key('q'),
    ] {
        tx.send(ev).unwrap();
    }
    // Tiny terminal on purpose: snapshots stay readable.
    let mut terminal = Terminal::new(TestBackend::new(30, 7)).unwrap();
    run(&mut terminal, &mut app, &Theme::default(), &rx).unwrap();

    assert!(!app.running);
    assert_snapshot!(terminal.backend());
}
```

The snapshot `cargo insta review` shows:

```
"╭ dirsize · by size ─────────╮"
"│b                         3M│"
"│a                       512B│"
"│c                          …│"
"│                            │"
"│                            │"
"╰ j/k move  s sort  q quit ──╯"
```

- **Keep test terminals tiny** (Orhun uses 20x10 and 40x10): "so that I won't
  have huge strings in tests".
- **Snapshots ignore color and style.** Where styling matters, render a widget
  into `Buffer::empty(rect)` and compare with
  `Buffer::with_lines([...])` plus `.set_style(...)` using `assert_eq!`
  (`assert_buffer_eq!` is deprecated).
- **End to end** (raw mode, teardown, exit code): run the real binary in a
  pty with `termlens`, the harness Ratatui's testing recipe now recommends.

**Let the agent see the screen.** A coding agent can drive the real binary
in a private tmux server and read the screen, the TUI equivalent of teeing a
server's logs to `logs/`:

```bash
T="tmux -L agent -f /dev/null"          # private server: never touches the user's tmux
$T new-session -d -x 60 -y 15 -s app "COLORTERM=truecolor ./target/debug/app; echo EXIT=\$?; sleep 30"
sleep 1; $T capture-pane -p -t app      # the screen as text
$T send-keys -t app j j Enter
$T capture-pane -p -e -t app            # -e keeps colors as SGR escapes
$T send-keys -t app q; sleep 0.5; $T capture-pane -p -t app | grep EXIT; $T kill-server
```

All the behavior claims in this file and in `tachyonfx.md` were checked this
way.

## Review checklist

- [ ] Does the TUI start only when stdout is a terminal, with JSON otherwise?
- [ ] Are other panic hooks installed before `ratatui::init`/`run`?
- [ ] Is anything enabled beyond raw mode and the alternate screen (mouse,
      paste, focus) turned off on exit and in the panic hook?
- [ ] Are keys filtered to `KeyEventKind::Press`, and is `Ctrl+c` handled?
- [ ] Do unknown events fall through instead of `unimplemented!()`?
- [ ] Is crossterm used only via `ratatui::crossterm` (one version in `cargo tree`)?
- [ ] Is slow work off the UI thread, reporting back over the channel?
- [ ] Does the loop block when idle?
- [ ] Is `run` generic over `Backend` and fed by a channel, with a snapshot test?
- [ ] Are logs going to a file, not the screen?

## Further reading

- Orhun Parmaksız's talks:
  [Introducing Ratatui](https://www.youtube.com/watch?v=NU0q6NOLJ20) (FOSDEM 2024),
  [Renaissance of Terminal User Interfaces with Rust](https://www.youtube.com/watch?v=hWG51Mc1DlM) (EuroRust 2024),
  [Bringing Terminal Aesthetics to the Web](https://www.youtube.com/watch?v=iepbyYrF_YQ) (FOSDEM 2025),
  [If it can compute, it can run Ratatui](https://www.youtube.com/watch?v=btqNDDuZ3cI) (Rust Nation UK 2026),
  and the [Developer Voices interview](https://www.youtube.com/watch?v=CNVmIocyDOQ) (2024)
  on architecture and testing.
  His full list: [recorded talks playlist](https://youtube.com/playlist?list=PLxqHy2Zr5TiVVrNU19xVR07M9Jqb0XzFq).
- His apps, smallest first: [flawz](https://github.com/orhun/flawz) (the
  cleanest 0.30-era layout), [binsider](https://github.com/orhun/binsider),
  [systeroid](https://github.com/orhun/systeroid) (snapshot tests).
- [Rust Asia 2025 workshop](https://github.com/orhun/rustasia2025-ratatui-workshop):
  a chapter-by-chapter build of a resource monitor.
- [ratatui.rs](https://ratatui.rs): recipes for testing, panic hooks, and
  releasing. Some pages still show 0.28-era setup code; prefer
  `ratatui::run` and `Layout::vertical(..).areas(..)`. Read examples at the
  release tag: `main` already carries unreleased 0.31 changes.
