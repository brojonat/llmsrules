# Terminal slide decks with presenterm

[presenterm](https://github.com/mfontanini/presenterm) renders a markdown file
as slides in the terminal: themes, images and GIFs, highlighted code that
steps through a snippet, and live demos that run inside the deck. Orhun
Parmaksız gives every talk with it (16 public decks since 2024), and the
patterns below are his. The deck is a text file in git, so it diffs, reviews
and hot-reloads like code.

Checked with presenterm 0.16.1 (the current release; `master` has unreleased
features such as `bg_image`, so stick to 0.16.1 syntax), rendered in a tmux
session and linted headlessly. Orhun's habits come from his talk repos
(`orhun/beyond-text`, `fosdem2025`, `eurorust2024`, `rust-uis-to-the-terminal`, ...).

## A talk repo

One repository per talk:

```
presentation.md          the deck
assets/                  images and GIFs
config/presenterm.yml    presenterm config for this talk
config/wezterm.lua       the terminal it's presented in (Orhun's)
present.sh               launches the terminal + presenterm
mise.toml                tools and tasks
README.md                abstract, event, recording link, how to present
```

Demo code comes in as git submodules (fosdem2025: ratatui, tachyonfx,
ratzilla) or as prebuilt binaries. The README links the recording once it
exists; one talk also commits an exported PDF, and one keeps a translation
as `presentation_jp.md`.

```toml
# mise.toml
[tools]
"github:mfontanini/presenterm" = "0.16.1"   # no short name in mise's registry

[tasks.dev]
description = "Edit mode: hot reload on save"
run = "presenterm -X -c config/presenterm.yml presentation.md"

[tasks.present]
description = "Presentation mode (no hot reload)"
run = "presenterm -X -p -c config/presenterm.yml presentation.md"

[tasks.lint]
description = "Parse the deck headlessly (exits non-zero on errors)"
# presenterm prints errors on stdout, so keep everything in a log and show its tail on failure.
run = 'mkdir -p logs; presenterm -c config/presenterm.yml --export-html presentation.md -o logs/deck.html < /dev/null > logs/lint.log 2>&1 || { tail -n 3 logs/lint.log; exit 1; }'
```

```yaml
# config/presenterm.yml
# yaml-language-server: $schema=https://raw.githubusercontent.com/mfontanini/presenterm/master/config-file-schema.json
defaults:
  image_protocol: auto
transition:
  duration_millis: 300
  frames: 45
  animation:
    style: fade
snippet:
  exec:
    enable: true          # +exec without -x; -X on the CLI covers +exec_replace
export:
  dimensions:             # lets --export-html run without a terminal (lint)
    columns: 100
    rows: 30
```

Orhun's `present.sh` opens a dedicated WezTerm window (JetBrains Mono at size
25, Gruvbox colors, no tab bar) so the talk doesn't depend on the laptop's
everyday terminal setup:

```bash
#!/usr/bin/env bash
[ -z "$PRESENT_MODE" ] && args="" || args="-p"
wezterm --config-file config/wezterm.lua \
  start presenterm "$PWD"/presentation.md \
  --config-file "$PWD"/config/presenterm.yml -X $args &
```

`./present.sh` while writing (hot reload), `PRESENT_MODE=1 ./present.sh` on
stage.

## Deck syntax

Front matter, then slides, each ending with `<!-- end_slide -->`. **`---`
is a horizontal rule, not a slide break.** Single-line HTML comments are
commands.

```markdown
---
theme:
  name: catppuccin-mocha
  override:
    footer:
      style: template
      left: "@me.dev"
      right: "Rust Meetup 2026"
---

<!-- new_lines: 2 -->
<!-- alignment: center -->

<span style="color: #ffd970">**dirsize:**</span>  
<span style="color: #ffd970">**a Ratatui app in 200 lines**</span>

---

<span style="color: #ff7a36">**Your Name**</span>

<!-- end_slide -->
```

(Two trailing spaces force a line break.)

| Command | Effect |
|---|---|
| `<!-- pause -->` | reveal the rest on the next key press |
| `<!-- jump_to_middle -->` | center vertically: section dividers, punchlines |
| `<!-- column_layout: [2, 5] -->`, `<!-- column: 0 -->`, `<!-- reset_layout -->` | columns, sized by ratio |
| `<!-- alignment: center -->` | align the rest of the slide |
| `<!-- new_lines: 2 -->` | vertical space |
| `<!-- no_footer -->` | hide the footer on this slide |
| `<!-- speaker_note: ... -->` | notes for `-l` in a second terminal (`-P` here) |
| `<!-- // anything -->` | a comment that isn't a command |

Built-in themes include `catppuccin-mocha`, `tokyonight-storm`,
`gruvbox-dark`, `terminal-dark` and `dark`; `override:` changes parts of one.
Footer templates can use `{current_slide}`, `{total_slides}`, and front
matter fields; **referencing a field the front matter doesn't set (such as
`{date}`) is an error.**

Images: `![image:width:80%](assets/demo.gif)`, relative to the deck, local
files only.

Code blocks take attributes after the language:

````markdown
```rust {1-6|2|3|4-5|1-6} +line_numbers
while app.running {
    terminal.draw(|f| ui::render(app, theme, f))?;
    match events.recv()? {
        Event::Key(key) => app.run_command(Command::from(key)),
        _ => {}
    }
}
```
````

Each `|` group is one step: the listed lines stay bright, the rest dim
(checked: line 1 turns gray on step 2).

## How Orhun builds a deck

Counted across his 16 decks:

- **One idea per slide, mostly visual.** A short heading (or none), one image
  or GIF at 80-100% width, a centered one-line caption, and a bare link
  (`[](https://github.com/...)` renders the URL itself). Many slides are a
  GIF and nothing else.
- **`pause` everywhere** (635 uses): reveal bullets and punchlines one at a
  time; ask the audience a question, then pause.
- **Section dividers and reactions with `jump_to_middle`**: a bold all-caps
  line with a block cursor (`**RUST IN THE TERMINAL █**`), or content, then
  `pause`, then `jump_to_middle` and a reaction GIF.
- **A hand-made title slide**, not the front matter's generated intro:
  logo GIF, colored bold `<span>` title, a `---` rule, name, roles. Newer
  decks put only a theme and a footer override in the front matter.
- **Footer**: handle on the left, event on the right, and `<!-- no_footer -->`
  on nearly every content slide, so it mostly shows on the title slide.
- **A "who am I" slide** in a two-column layout: avatar left, bio right.
- **Code is shown, never run.** 88 `rust` blocks, zero `rust +exec`. He walks
  through a snippet with dynamic highlighting that starts and ends on the
  full range (`{1-20|5|6|7,16-18|1-20}`), or builds it up over several
  blocks separated by `pause`.
- **Diagrams are box-drawing text** in a plain code block; no mermaid or
  typst rendering.
- **Speaker notes almost never** (one in all decks): the slides are sparse
  enough that he talks over them.

## Live demos

The reason to present from a terminal: the demo runs where the slides are.

````markdown
```bash +exec +acquire_terminal
cargo run --release --manifest-path demos/dirsize/Cargo.toml -- ~/projects
```
````

`+exec +acquire_terminal`: press `Ctrl-e` and presenterm hands the real
terminal to the program; quit it to come back to the slide. This is how he
runs interactive TUIs (83 uses).

````markdown
<!-- column_layout: [2, 5] -->
<!-- column: 0 -->

## Widgets

- Table
- Block

<!-- column: 1 -->

```bash +exec_replace +pty
./target/release/dirsize ~/projects
```
````

`+exec_replace +pty` runs the program when the slide loads and draws its
screen inside the slide, here next to a list. Checked: a Ratatui app renders
live in the column. `+pty` takes **no keyboard input**, so it's for things
that animate on their own (Ratatui's `demo`, `sparkline` and `chart`
examples in his decks). Plain `+pty` sizes itself to the column; an explicit
`+pty:COLS:ROWS` wider than the column wraps every line.

Other demo moves of his: `mpv --loop-file assets/clip.mp4` in a `bash +exec`
block for video, `handlr open https://...` to open a browser, and prebuilt
release binaries (absolute paths) so nothing compiles on stage.

**Execution flags**: `+exec` needs `-x` or `snippet.exec.enable: true`;
`+exec_replace` and `+image` need `-X`. `-X` does not imply `-x`, hence the
config plus `-X` above. Without them the blocks render as plain code.

## Checking a deck

- **`mise run lint`** (above) parses every slide without a terminal and
  exits 1 on errors. It needs `export.dimensions` in the config; without it,
  export fails with `Inappropriate ioctl for device`.
- **Errors go to stdout.** A broken deck exits 1 with nothing on stderr, so
  a lint that throws stdout away hides the reason.
- **See it the way the audience will.** Render in a private tmux server and
  step through it, as in [`tui.md`](tui.md#testing):
  ```bash
  T="tmux -L agent -f /dev/null"
  $T new-session -d -x 100 -y 28 -s deck "presenterm -X -c config/presenterm.yml presentation.md"
  sleep 2; $T capture-pane -p -t deck          # slide 1
  $T send-keys -t deck l; sleep 0.5; $T capture-pane -p -t deck
  $T kill-server
  ```
  Every `pause` and every highlight step takes one key press, so count them.
- **`--validate-overflows`** in a real terminal at the presenting size
  catches slides that don't fit.

## Gotchas

1. **A one-line comment that isn't a command stops the deck from loading**:
   `<!-- remember to demo -->` fails with
   `invalid command: unknown variant 'remember to demo'`. Write
   `<!-- // remember to demo -->`.
2. **`---` doesn't end a slide.** Use `<!-- end_slide -->`.
3. **Images need a graphics-capable terminal**: kitty, WezTerm, iTerm2,
   Ghostty, foot (or sixel); others get ASCII blocks. Under tmux add
   `set -g allow-passthrough on`. **GIFs don't animate in Ghostty** (issue
   #699); Orhun presents in WezTerm and forces `image_protocol: iterm2` in
   his newest deck.
4. **`-p` turns off hot reload.** Write without it.
5. **`font_size` works only in kitty 0.40+**, and not inside tmux.
6. **PDF export needs weasyprint** (`uv run --with weasyprint presenterm --export-pdf ...`),
   and exports drop `pause`s unless `export.pauses: new_slide` is set.

## Review checklist

- [ ] Does every slide end with `<!-- end_slide -->`?
- [ ] Are all non-command comments written `<!-- // ... -->`?
- [ ] Does `mise run lint` pass?
- [ ] One idea per slide, with `pause` for reveals?
- [ ] Is code walked through with highlight steps rather than shown all at once?
- [ ] Are demo binaries prebuilt, interactive ones on `+acquire_terminal`?
- [ ] Do `+pty` panels fit their column?
- [ ] Does the README say how to present it (`./present.sh`, terminal, flags)?

## Further reading

- [presenterm docs](https://mfontanini.github.io/presenterm/): every command,
  theme key and config option.
- Orhun's decks: [beyond-text](https://github.com/orhun/beyond-text) (newest
  style), [fosdem2025](https://github.com/orhun/fosdem2025) (submodule
  demos), [eurorust2024](https://github.com/orhun/eurorust2024), and the
  recordings in his [talks playlist](https://youtube.com/playlist?list=PLxqHy2Zr5TiVVrNU19xVR07M9Jqb0XzFq).
