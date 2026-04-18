---
name: bubbletea
description: Build terminal user interfaces (TUIs) in Go with the Charm Bubble Tea framework (Elm-style Model/Update/View). Use when creating or modifying interactive CLI apps, dashboards, wizards, pickers, progress UIs, pagers, or any Go program that uses github.com/charmbracelet/bubbletea, github.com/charmbracelet/bubbles, or github.com/charmbracelet/lipgloss. Triggers on tasks involving tea.Model, tea.Cmd, tea.Msg, tea.KeyMsg, spinners, text inputs, lists, tables, viewports, progress bars, paginators, or styling terminal output.
---

# Bubble Tea TUI (Go)

Bubble Tea is a Go framework for building terminal user interfaces based on **The Elm Architecture**: immutable **Model**, pure **Update** function that returns a new model and a `Cmd`, and a pure **View** function that renders a string. Async work (HTTP, timers, I/O) is dispatched as `tea.Cmd` values that return `tea.Msg` values, which are delivered back to `Update`.

- `github.com/charmbracelet/bubbletea` - core runtime (v1 stable; use `/v2` for v2)
- `github.com/charmbracelet/bubbles` - ready-made components (spinner, textinput, list, table, viewport, progress, paginator, help, key, textarea, stopwatch, timer, filepicker)
- `github.com/charmbracelet/lipgloss` - styling (colors, borders, padding, layout)

This skill targets the **v1 API** on `github.com/charmbracelet/bubbletea` because that is still the most widely deployed module path. A short migration note at the end covers v2 (`github.com/charmbracelet/bubbletea/v2`).

## 1. Minimal program

```go
package main

import (
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
)

type model struct {
	cursor   int
	choices  []string
	selected map[int]struct{}
}

func initialModel() model {
	return model{
		choices:  []string{"Buy carrots", "Buy celery", "Buy kohlrabi"},
		selected: make(map[int]struct{}),
	}
}

// Init runs once when the program starts. Return any startup Cmd (or nil).
func (m model) Init() tea.Cmd {
	return tea.SetWindowTitle("Grocery List")
}

// Update is called for every message. It MUST be pure: take a model, return a
// new model and optionally a Cmd. Never mutate external state here.
func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c", "q":
			return m, tea.Quit
		case "up", "k":
			if m.cursor > 0 {
				m.cursor--
			}
		case "down", "j":
			if m.cursor < len(m.choices)-1 {
				m.cursor++
			}
		case "enter", " ":
			if _, ok := m.selected[m.cursor]; ok {
				delete(m.selected, m.cursor)
			} else {
				m.selected[m.cursor] = struct{}{}
			}
		}
	}
	return m, nil
}

// View renders the current UI as a string. Called after every Update.
func (m model) View() string {
	s := "What should we buy?\n\n"
	for i, choice := range m.choices {
		cursor := " "
		if m.cursor == i {
			cursor = ">"
		}
		checked := " "
		if _, ok := m.selected[i]; ok {
			checked = "x"
		}
		s += fmt.Sprintf("%s [%s] %s\n", cursor, checked, choice)
	}
	s += "\nPress q to quit.\n"
	return s
}

func main() {
	p := tea.NewProgram(initialModel())
	if _, err := p.Run(); err != nil {
		fmt.Printf("Alas, there's been an error: %v", err)
		os.Exit(1)
	}
}
```

### The `tea.Model` interface

```go
type Model interface {
	Init() Cmd
	Update(Msg) (Model, Cmd)
	View() string
}

type Msg interface{}   // any value, type-switched in Update
type Cmd func() Msg    // async work; runs in its own goroutine
```

**Use value receivers**, not pointer receivers, for the Model methods. The runtime treats the returned model as the new state. Mutating in-place through a pointer still works, but the idiomatic pattern is to return a modified copy — it keeps `Update` pure and makes concurrency safe.

## 2. Commands and messages

A `tea.Cmd` is a function `func() tea.Msg` that Bubble Tea runs on a goroutine. Whatever `Msg` it returns is fed back into `Update`. This is how you do **any** async or side-effectful work: HTTP calls, reading files, timers, shelling out, receiving from channels.

```go
type statusMsg int
type errMsg struct{ err error }
func (e errMsg) Error() string { return e.err.Error() }

// A Cmd is just a func returning a Msg. Signature: func() tea.Msg
func checkServer() tea.Msg {
	c := &http.Client{Timeout: 10 * time.Second}
	res, err := c.Get("https://charm.sh/")
	if err != nil {
		return errMsg{err}
	}
	defer res.Body.Close()
	return statusMsg(res.StatusCode)
}

func (m model) Init() tea.Cmd { return checkServer }

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case statusMsg:
		m.status = int(msg)
		return m, tea.Quit
	case errMsg:
		m.err = msg
		return m, tea.Quit
	case tea.KeyMsg:
		if msg.Type == tea.KeyCtrlC {
			return m, tea.Quit
		}
	}
	return m, nil
}
```

### Commands that take arguments

Return a closure:

```go
func fetch(url string) tea.Cmd {
	return func() tea.Msg {
		resp, err := http.Get(url)
		if err != nil {
			return errMsg{err}
		}
		defer resp.Body.Close()
		b, _ := io.ReadAll(resp.Body)
		return bodyMsg(b)
	}
}

// usage: return m, fetch("https://example.com")
```

### Composing commands

- `tea.Batch(cmds...)` - run in parallel, messages arrive in any order.
- `tea.Sequence(cmds...)` - run one after the other, waiting for each to complete.
- `tea.Tick(d, fn)` - fire a single message after a duration.
- `tea.Every(d, fn)` - fire a message on a recurring interval (aligned to wall clock).
- `tea.Printf` / `tea.Println` - print above the TUI (inline mode) as a Cmd.

```go
func tickEverySecond() tea.Cmd {
	return tea.Tick(time.Second, func(t time.Time) tea.Msg {
		return tickMsg(t)
	})
}

// Re-arm inside Update to keep ticking:
case tickMsg:
	return m, tickEverySecond()
```

### Sending messages from outside the Elm loop

Pass the `*tea.Program` into a goroutine and call `p.Send(msg)`:

```go
var p *tea.Program

func main() {
	p = tea.NewProgram(model{})
	go func() {
		for event := range externalChan {
			p.Send(externalMsg(event))
		}
	}()
	if _, err := p.Run(); err != nil { log.Fatal(err) }
}
```

## 3. Handling keyboard input

`tea.KeyMsg` comes in on every keystroke. Three common ways to match:

```go
case tea.KeyMsg:
	// 1. By string representation (most common)
	switch msg.String() {
	case "ctrl+c", "q", "esc":
		return m, tea.Quit
	case "enter", " ":
		// ...
	case "up", "k":
		// ...
	}

	// 2. By KeyType (enum) for special keys
	switch msg.Type {
	case tea.KeyEnter, tea.KeyCtrlC, tea.KeyEsc:
		return m, tea.Quit
	case tea.KeyTab, tea.KeyShiftTab:
		// ...
	}

	// 3. Raw runes for printable characters
	if msg.Type == tea.KeyRunes {
		for _, r := range msg.Runes { /* ... */ }
	}
```

### Structured keybindings via `bubbles/key`

Prefer this pattern for real apps - it makes help text automatic:

```go
import "github.com/charmbracelet/bubbles/key"

type keyMap struct {
	Up, Down, Help, Quit key.Binding
}

var keys = keyMap{
	Up:   key.NewBinding(key.WithKeys("up", "k"), key.WithHelp("↑/k", "up")),
	Down: key.NewBinding(key.WithKeys("down", "j"), key.WithHelp("↓/j", "down")),
	Help: key.NewBinding(key.WithKeys("?"), key.WithHelp("?", "toggle help")),
	Quit: key.NewBinding(key.WithKeys("q", "esc", "ctrl+c"), key.WithHelp("q", "quit")),
}

// In Update:
case tea.KeyMsg:
	switch {
	case key.Matches(msg, keys.Up):   /* ... */
	case key.Matches(msg, keys.Down): /* ... */
	case key.Matches(msg, keys.Quit): return m, tea.Quit
	}
```

Toggle bindings dynamically with `keys.Foo.SetEnabled(false)` so the help view hides them contextually.

## 4. Program options

```go
p := tea.NewProgram(
	model{},
	tea.WithAltScreen(),        // take over the full terminal
	tea.WithMouseCellMotion(),  // enable mouse (cell-level motion only)
	// tea.WithMouseAllMotion() // enable mouse (track every motion event)
	tea.WithContext(ctx),       // propagate cancellation
	tea.WithOutput(os.Stderr),  // render to a custom writer
	tea.WithInput(inputReader), // use a custom input source (SSH, tests)
	tea.WithFPS(60),            // cap renders per second
	tea.WithoutCatchPanics(),   // let panics through (debugging)
	tea.WithoutSignalHandler(), // don't install SIGINT handler
	tea.WithFilter(func(m tea.Model, msg tea.Msg) tea.Msg {
		// intercept/rewrite any message before Update sees it
		return msg
	}),
)
```

### Runtime commands that toggle screen state

These are also messages you can return from `Update`:

- `tea.EnterAltScreen`, `tea.ExitAltScreen`
- `tea.EnableMouseCellMotion`, `tea.EnableMouseAllMotion`, `tea.DisableMouse`
- `tea.HideCursor`, `tea.ShowCursor`
- `tea.ClearScreen`
- `tea.EnableBracketedPaste`, `tea.DisableBracketedPaste`
- `tea.EnableReportFocus`, `tea.DisableReportFocus`
- `tea.Suspend` (with `tea.ResumeMsg` arriving after)
- `tea.SetWindowTitle("...")`

```go
case " ":
	var cmd tea.Cmd
	if m.altscreen {
		cmd = tea.ExitAltScreen
	} else {
		cmd = tea.EnterAltScreen
	}
	m.altscreen = !m.altscreen
	return m, cmd
```

## 5. Window sizing and responsive layout

Bubble Tea sends a `tea.WindowSizeMsg` on startup and whenever the terminal resizes. Store the width/height on your model and propagate them to child components.

```go
type model struct {
	width, height int
	viewport      viewport.Model
	ready         bool
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height

		headerH := lipgloss.Height(m.headerView())
		footerH := lipgloss.Height(m.footerView())
		vMargin := headerH + footerH

		if !m.ready {
			m.viewport = viewport.New(msg.Width, msg.Height-vMargin)
			m.viewport.SetContent(m.content)
			m.ready = true
		} else {
			m.viewport.Width = msg.Width
			m.viewport.Height = msg.Height - vMargin
		}
	}
	// ...
}
```

Call `tea.WindowSize()` as a `Cmd` to request a size message on demand (useful after returning from a suspended state).

## 6. Styling with lipgloss

```go
import "github.com/charmbracelet/lipgloss"

var style = lipgloss.NewStyle().
	Bold(true).
	Foreground(lipgloss.Color("#FAFAFA")).
	Background(lipgloss.Color("#7D56F4")).
	PaddingTop(2).
	PaddingLeft(4).
	Width(22)

fmt.Println(style.Render("Hello, kitty"))
```

### Colors

- ANSI-16: `lipgloss.Color("5")`
- ANSI-256: `lipgloss.Color("86")`
- True color: `lipgloss.Color("#0000FF")`
- Adapt to light/dark terminals: `lipgloss.AdaptiveColor{Light: "236", Dark: "248"}`
- Explicit per-profile: `lipgloss.CompleteColor{TrueColor: "#0000FF", ANSI256: "21", ANSI: "4"}`

### Text attributes

`Bold`, `Italic`, `Faint`, `Underline`, `Strikethrough`, `Reverse`, `Blink`.

### Box model (CSS-like shorthands)

```go
s := lipgloss.NewStyle().
	Padding(2).             // all sides
	Margin(1, 4).           // vertical, horizontal
	Padding(1, 4, 2, 1).    // top, right, bottom, left (clockwise)
	Width(40).Height(10).
	Align(lipgloss.Center)  // horizontal alignment
```

### Borders

```go
lipgloss.NewStyle().
	BorderStyle(lipgloss.RoundedBorder()).   // NormalBorder, ThickBorder, DoubleBorder, HiddenBorder, ASCIIBorder
	BorderForeground(lipgloss.Color("228")).
	BorderTop(true).
	BorderLeft(true)

// Custom border:
b := lipgloss.Border{Top: "─", Bottom: "─", Left: "│", Right: "│",
	TopLeft: "╭", TopRight: "╮", BottomLeft: "╰", BottomRight: "╯"}
```

### Composition

```go
lipgloss.JoinHorizontal(lipgloss.Top, left, right)       // side-by-side
lipgloss.JoinVertical(lipgloss.Left, header, body, footer)
lipgloss.Place(w, h, lipgloss.Center, lipgloss.Center, s) // center within a box

lipgloss.Width(s)   // measure rendered width (honoring ANSI)
lipgloss.Height(s)  // measure rendered height
```

### Inheritance and unset

```go
base := lipgloss.NewStyle().Foreground(lipgloss.Color("63"))
bold := lipgloss.NewStyle().Inherit(base).Bold(true)
plain := bold.UnsetBold()
```

## 7. Bubbles: ready-made components

All Bubbles components follow a mini Elm loop of their own with `Init() tea.Cmd`, `Update(tea.Msg) (Model, tea.Cmd)`, and `View() string`. Embed them on your parent model and **forward messages** in `Update`.

### spinner

```go
import "github.com/charmbracelet/bubbles/spinner"

type model struct{ spinner spinner.Model }

func initial() model {
	s := spinner.New()
	s.Spinner = spinner.Dot // Line, MiniDot, Jump, Pulse, Points, Globe, Moon, Monkey, ...
	s.Style = lipgloss.NewStyle().Foreground(lipgloss.Color("205"))
	return model{spinner: s}
}

func (m model) Init() tea.Cmd { return m.spinner.Tick }

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmd tea.Cmd
	m.spinner, cmd = m.spinner.Update(msg)
	return m, cmd
}

func (m model) View() string {
	return fmt.Sprintf("%s loading...", m.spinner.View())
}
```

### textinput

```go
import "github.com/charmbracelet/bubbles/textinput"

ti := textinput.New()
ti.Placeholder = "Pikachu"
ti.Focus()
ti.CharLimit = 156
ti.Width = 20
// ti.EchoMode = textinput.EchoPassword; ti.EchoCharacter = '•'

func (m model) Init() tea.Cmd { return textinput.Blink }

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmd tea.Cmd
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.Type {
		case tea.KeyEnter:
			// submit: m.textInput.Value()
			return m, tea.Quit
		case tea.KeyCtrlC, tea.KeyEsc:
			return m, tea.Quit
		}
	}
	m.textInput, cmd = m.textInput.Update(msg)
	return m, cmd
}
```

### Multi-input form (tab to cycle)

```go
type model struct {
	focusIndex int
	inputs     []textinput.Model
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "tab", "shift+tab", "up", "down":
			if msg.String() == "up" || msg.String() == "shift+tab" {
				m.focusIndex--
			} else {
				m.focusIndex++
			}
			if m.focusIndex >= len(m.inputs) { m.focusIndex = 0 }
			if m.focusIndex < 0 { m.focusIndex = len(m.inputs) - 1 }

			cmds := make([]tea.Cmd, len(m.inputs))
			for i := range m.inputs {
				if i == m.focusIndex {
					cmds[i] = m.inputs[i].Focus()
				} else {
					m.inputs[i].Blur()
				}
			}
			return m, tea.Batch(cmds...)
		}
	}
	// forward to all; only focused ones actually react
	cmds := make([]tea.Cmd, len(m.inputs))
	for i := range m.inputs {
		m.inputs[i], cmds[i] = m.inputs[i].Update(msg)
	}
	return m, tea.Batch(cmds...)
}
```

### textarea

```go
import "github.com/charmbracelet/bubbles/textarea"

ta := textarea.New()
ta.Placeholder = "Say something..."
ta.Focus()
ta.CharLimit = 280
// forward msgs like textinput; read with ta.Value()
```

### list

```go
import "github.com/charmbracelet/bubbles/list"

type item string
func (i item) FilterValue() string { return string(i) }

// Minimal custom delegate:
type delegate struct{}
func (delegate) Height() int                               { return 1 }
func (delegate) Spacing() int                              { return 0 }
func (delegate) Update(_ tea.Msg, _ *list.Model) tea.Cmd   { return nil }
func (delegate) Render(w io.Writer, m list.Model, index int, li list.Item) {
	it, ok := li.(item)
	if !ok { return }
	prefix := "  "
	if index == m.Index() { prefix = "> " }
	fmt.Fprint(w, prefix+string(it))
}

l := list.New([]list.Item{item("Alpha"), item("Bravo")}, delegate{}, 30, 14)
l.Title = "Pick one"
l.SetShowStatusBar(false)
l.SetFilteringEnabled(true)

// In Update, forward and respond to window sizes:
case tea.WindowSizeMsg:
	m.list.SetSize(msg.Width, msg.Height)
case tea.KeyMsg:
	if msg.String() == "enter" {
		if it, ok := m.list.SelectedItem().(item); ok {
			m.choice = string(it)
		}
	}
m.list, cmd = m.list.Update(msg)
```

For a batteries-included default, use `list.NewDefaultDelegate()` and items that implement both `Title() string` and `Description() string`.

### viewport (scrollable pager)

```go
import "github.com/charmbracelet/bubbles/viewport"

case tea.WindowSizeMsg:
	if !m.ready {
		m.viewport = viewport.New(msg.Width, msg.Height-headerFooterHeight)
		m.viewport.SetContent(m.content)
		m.ready = true
	} else {
		m.viewport.Width = msg.Width
		m.viewport.Height = msg.Height - headerFooterHeight
	}

// always forward key/mouse for scroll:
m.viewport, cmd = m.viewport.Update(msg)
```

Enable mouse wheel scrolling with `tea.WithMouseCellMotion()` in program options. `m.viewport.ScrollPercent()` gives the current scroll ratio for status bars.

### progress

```go
import "github.com/charmbracelet/bubbles/progress"

pb := progress.New(progress.WithDefaultGradient())
// or: progress.WithScaledGradient("#FF7CCB", "#FDFF8C")
// or: progress.WithSolidFill("63")

// Animated set:
case progressMsg: // your own msg carrying a float64 percentage
	cmd := m.progress.SetPercent(float64(msg))
	return m, cmd

case progress.FrameMsg:
	var cmd tea.Cmd
	newModel, cmd := m.progress.Update(msg)
	m.progress = newModel.(progress.Model)
	return m, cmd

// View: m.progress.View()
```

Set width after window size messages: `m.progress.Width = msg.Width - padding`.

### paginator

```go
import "github.com/charmbracelet/bubbles/paginator"

p := paginator.New()
p.Type = paginator.Dots       // or paginator.Arabic
p.PerPage = 10
p.ActiveDot   = lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "235", Dark: "252"}).Render("•")
p.InactiveDot = lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "250", Dark: "238"}).Render("•")
p.SetTotalPages(len(items))

// In View:
start, end := m.paginator.GetSliceBounds(len(m.items))
for _, it := range m.items[start:end] { /* render */ }
sb.WriteString(m.paginator.View())

// Forward in Update:
m.paginator, cmd = m.paginator.Update(msg)
```

### table

```go
import "github.com/charmbracelet/bubbles/table"

cols := []table.Column{
	{Title: "Rank", Width: 4},
	{Title: "City", Width: 20},
}
rows := []table.Row{{"1", "Tokyo"}, {"2", "Delhi"}}

t := table.New(
	table.WithColumns(cols),
	table.WithRows(rows),
	table.WithFocused(true),
	table.WithHeight(7),
)

s := table.DefaultStyles()
s.Header = s.Header.BorderStyle(lipgloss.NormalBorder()).
	BorderForeground(lipgloss.Color("240")).BorderBottom(true).Bold(false)
s.Selected = s.Selected.Foreground(lipgloss.Color("229")).
	Background(lipgloss.Color("57")).Bold(false)
t.SetStyles(s)

// In Update:
switch msg := msg.(type) {
case tea.KeyMsg:
	switch msg.String() {
	case "enter":
		return m, tea.Batch(tea.Printf("chose %s", m.table.SelectedRow()[1]))
	case "esc":
		if m.table.Focused() { m.table.Blur() } else { m.table.Focus() }
	}
}
m.table, cmd = m.table.Update(msg)
```

### help

```go
import (
	"github.com/charmbracelet/bubbles/help"
	"github.com/charmbracelet/bubbles/key"
)

type keyMap struct{ Up, Down, Help, Quit key.Binding }

func (k keyMap) ShortHelp() []key.Binding { return []key.Binding{k.Help, k.Quit} }
func (k keyMap) FullHelp() [][]key.Binding {
	return [][]key.Binding{{k.Up, k.Down}, {k.Help, k.Quit}}
}

h := help.New()

// View:
helpView := m.help.View(m.keys) // one-liner; m.help.ShowAll = true for full view

// Resize:
case tea.WindowSizeMsg:
	m.help.Width = msg.Width
```

### timer / stopwatch

```go
import "github.com/charmbracelet/bubbles/timer"

m.timer = timer.New(time.Minute)

func (m model) Init() tea.Cmd { return m.timer.Init() }

case timer.TickMsg:
	m.timer, cmd = m.timer.Update(msg)
case timer.StartStopMsg:
	m.timer, cmd = m.timer.Update(msg)
case timer.TimeoutMsg:
	return m, tea.Quit
```

Stopwatch has the same shape (`stopwatch.New()`, `stopwatch.TickMsg`, `Start/Stop/Reset`).

### filepicker

```go
import "github.com/charmbracelet/bubbles/filepicker"

fp := filepicker.New()
fp.AllowedTypes = []string{".go", ".md"}
fp.CurrentDirectory, _ = os.UserHomeDir()

// In Update, forward msgs:
m.fp, cmd = m.fp.Update(msg)
if didSelect, path := m.fp.DidSelectFile(msg); didSelect {
	m.selected = path
}
```

## 8. Common patterns

### Loading state while an async op runs

```go
type doneMsg struct{ result string }

func loadStuff() tea.Cmd {
	return func() tea.Msg {
		time.Sleep(2 * time.Second)
		return doneMsg{result: "fetched"}
	}
}

type model struct {
	spinner  spinner.Model
	loading  bool
	result   string
}

func (m model) Init() tea.Cmd {
	return tea.Batch(m.spinner.Tick, loadStuff())
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case doneMsg:
		m.loading = false
		m.result = msg.result
		return m, nil
	case tea.KeyMsg:
		if msg.String() == "q" { return m, tea.Quit }
	}
	var cmd tea.Cmd
	m.spinner, cmd = m.spinner.Update(msg)
	return m, cmd
}

func (m model) View() string {
	if m.loading {
		return fmt.Sprintf("%s loading...", m.spinner.View())
	}
	return "Result: " + m.result
}
```

### Multi-screen navigation (state machine)

Keep an enum of screens on the model and dispatch in `Update` and `View`:

```go
type screen int
const (
	screenMenu screen = iota
	screenForm
	screenResult
)

type model struct {
	screen screen
	menu   list.Model
	form   formModel
	result string
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch m.screen {
	case screenMenu:
		return m.updateMenu(msg)
	case screenForm:
		return m.updateForm(msg)
	case screenResult:
		return m.updateResult(msg)
	}
	return m, nil
}

func (m model) View() string {
	switch m.screen {
	case screenMenu:   return m.menu.View()
	case screenForm:   return m.form.View()
	case screenResult: return m.result
	}
	return ""
}
```

Each sub-update returns `m, cmd` and can change `m.screen` to transition.

### Modal dialog overlay

Store a `modal *modalModel` on the parent. When non-nil, render it on top:

```go
func (m model) View() string {
	base := m.mainView()
	if m.modal == nil { return base }
	dialog := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		Padding(1, 2).
		Render(m.modal.View())
	return lipgloss.Place(
		m.width, m.height,
		lipgloss.Center, lipgloss.Center,
		dialog,
		lipgloss.WithWhitespaceChars(" "),
	)
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if m.modal != nil {
		// let the modal consume messages; swallow keys from the base
		var cmd tea.Cmd
		*m.modal, cmd = m.modal.Update(msg)
		if m.modal.done { m.modal = nil }
		return m, cmd
	}
	return m.baseUpdate(msg)
}
```

### Composable/embedded models (tab layout)

```go
type sessionState uint
const (
	timerView sessionState = iota
	spinnerView
)

type mainModel struct {
	state   sessionState
	timer   timer.Model
	spinner spinner.Model
}

func (m mainModel) Init() tea.Cmd {
	return tea.Batch(m.timer.Init(), m.spinner.Tick)
}

func (m mainModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd
	var cmd tea.Cmd
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c", "q":
			return m, tea.Quit
		case "tab":
			if m.state == timerView { m.state = spinnerView } else { m.state = timerView }
		}
		// only forward keys to the focused child:
		if m.state == spinnerView {
			m.spinner, cmd = m.spinner.Update(msg)
		} else {
			m.timer, cmd = m.timer.Update(msg)
		}
		cmds = append(cmds, cmd)
	case spinner.TickMsg:
		m.spinner, cmd = m.spinner.Update(msg)
		cmds = append(cmds, cmd)
	case timer.TickMsg:
		m.timer, cmd = m.timer.Update(msg)
		cmds = append(cmds, cmd)
	}
	return m, tea.Batch(cmds...)
}

func (m mainModel) View() string {
	box := lipgloss.NewStyle().Width(15).Height(5).
		Align(lipgloss.Center, lipgloss.Center).
		BorderStyle(lipgloss.HiddenBorder())
	focused := box.BorderStyle(lipgloss.NormalBorder()).
		BorderForeground(lipgloss.Color("69"))
	if m.state == timerView {
		return lipgloss.JoinHorizontal(lipgloss.Top,
			focused.Render(m.timer.View()), box.Render(m.spinner.View()))
	}
	return lipgloss.JoinHorizontal(lipgloss.Top,
		box.Render(m.timer.View()), focused.Render(m.spinner.View()))
}
```

### Pager (viewport + header + footer)

```go
var (
	titleStyle = func() lipgloss.Style {
		b := lipgloss.RoundedBorder(); b.Right = "├"
		return lipgloss.NewStyle().BorderStyle(b).Padding(0, 1)
	}()
	infoStyle = func() lipgloss.Style {
		b := lipgloss.RoundedBorder(); b.Left = "┤"
		return titleStyle.BorderStyle(b)
	}()
)

func (m model) headerView() string {
	title := titleStyle.Render("Mr. Pager")
	line := strings.Repeat("─", max(0, m.viewport.Width-lipgloss.Width(title)))
	return lipgloss.JoinHorizontal(lipgloss.Center, title, line)
}

func (m model) footerView() string {
	info := infoStyle.Render(fmt.Sprintf("%3.f%%", m.viewport.ScrollPercent()*100))
	line := strings.Repeat("─", max(0, m.viewport.Width-lipgloss.Width(info)))
	return lipgloss.JoinHorizontal(lipgloss.Center, line, info)
}

func (m model) View() string {
	if !m.ready { return "\n  Initializing..." }
	return fmt.Sprintf("%s\n%s\n%s", m.headerView(), m.viewport.View(), m.footerView())
}

// Launch with alt-screen + mouse:
p := tea.NewProgram(model{content: string(b)},
	tea.WithAltScreen(), tea.WithMouseCellMotion())
```

### Mouse events

```go
p := tea.NewProgram(model{}, tea.WithMouseAllMotion())

case tea.MouseMsg:
	// msg.X, msg.Y, msg.Action (MouseActionPress/Release/Motion),
	// msg.Button (MouseButtonLeft/Right/Wheel...), msg.Alt/Ctrl/Shift
	return m, tea.Printf("(%d, %d) %s", msg.X, msg.Y, msg.String())
```

## 9. Logging and debugging

TUIs own stdout/stderr, so you can't `fmt.Println` for debugging while the program runs. Instead:

```go
if os.Getenv("DEBUG") != "" {
	f, err := tea.LogToFile("debug.log", "debug")
	if err != nil { log.Fatal(err) }
	defer f.Close()
}
// now log.Printf(...) writes to debug.log
```

Then `tail -f debug.log` in another pane. Or print above the TUI (only visible in inline mode, not alt-screen) with `tea.Println(...)` / `tea.Printf(...)` returned as a `Cmd`.

## 10. Testing TUIs with teatest

```go
import (
	"bytes"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/x/exp/teatest"
)

func TestMyModel(t *testing.T) {
	m := initialModel()
	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(80, 24))

	// Type keystrokes
	tm.Type("hello")

	// Send a synthetic message
	tm.Send(tea.KeyMsg{Type: tea.KeyEnter})

	// Wait until the rendered output matches a condition
	teatest.WaitFor(t, tm.Output(),
		func(bts []byte) bool {
			return bytes.Contains(bts, []byte("expected text"))
		},
		teatest.WithDuration(time.Second),
	)

	// Quit and assert final state
	tm.Send(tea.KeyMsg{Type: tea.KeyCtrlC})
	finalModel := tm.FinalModel(t).(model)
	if finalModel.choice != "hello" {
		t.Fatalf("want choice=hello, got %q", finalModel.choice)
	}

	// Or compare the final rendered output (golden-file friendly)
	out := tm.FinalOutput(t)
	teatest.RequireEqualOutput(t, out)
}
```

Key helpers:

- `teatest.NewTestModel(t, m, opts...)` - harness; `WithInitialTermSize(w, h)` is usually needed.
- `tm.Send(msg)` - inject any `tea.Msg`.
- `tm.Type("abc")` - send keystrokes.
- `tm.Output()` - `io.Reader` of the live render stream.
- `tm.FinalModel(t)` / `tm.FinalOutput(t)` - wait for exit, then inspect.
- `teatest.WaitFor(t, r, pred, opts...)` - block until render output satisfies `pred`.
- `teatest.RequireEqualOutput(t, bytes)` - golden-file comparison under `-update`.

## 11. Running a program

```go
p := tea.NewProgram(initialModel(), tea.WithAltScreen())
finalModel, err := p.Run()
if err != nil {
	log.Fatalf("alas: %v", err)
}
// finalModel is a tea.Model holding terminal state; type-assert to your concrete type:
if m, ok := finalModel.(model); ok {
	fmt.Println("chose:", m.choice)
}
```

Other `*tea.Program` methods worth knowing:

- `p.Send(msg)` - inject a message from outside (goroutines).
- `p.Quit()` - request shutdown.
- `p.Kill()` - force shutdown (returns `tea.ErrProgramKilled`).
- `p.Wait()` - block until the program finishes.
- `p.ReleaseTerminal()` / `p.RestoreTerminal()` - temporarily hand the TTY back (e.g. to shell out to `$EDITOR`). Or use `tea.ExecProcess(cmd, cb)` / `tea.Exec(...)` as a `Cmd`.

## 12. Conventions and gotchas

- **Pure Update.** Don't do I/O, sleep, or HTTP in `Update`. Return a `Cmd` for that.
- **Value receivers.** `func (m model) Update(...)` — returning a modified copy is the idiom.
- **Forward messages.** When you embed a Bubbles component, you must call `m.sub, cmd = m.sub.Update(msg)` in your `Update` or it won't animate/scroll/blink.
- **Always handle `tea.WindowSizeMsg`** if any child uses `Width`/`Height` (viewport, list, table, progress, help).
- **Handle `ctrl+c`.** Always map it to `tea.Quit` early in the switch.
- **Alt-screen + logs.** `fmt.Println` is swallowed when `WithAltScreen()` is on; use `tea.LogToFile`.
- **Batch, not chain.** When an Update branch wants to issue multiple commands, collect them and return `tea.Batch(cmds...)` — don't call `Update` recursively.
- **Rate-limit updates.** If an external source (channel, file watch) can flood `p.Send`, coalesce on the sender side; the renderer caps at 60 FPS by default.
- **Styles are immutable.** `s.Bold(true)` returns a new style; reassign if you want it to stick.

## 13. v2 migration notes (`github.com/charmbracelet/bubbletea/v2`)

If the project imports `github.com/charmbracelet/bubbletea/v2` (or `charm.land/bubbletea/v2`), key differences:

- `View()` returns `tea.View` (via `tea.NewView(s)`), not a plain `string`.
- Key input is split: prefer `tea.KeyPressMsg` (key-down) in `Update`. `Key` fields include `Mod` (e.g. `tea.ModCtrl`) and `Code` (a rune).
- `tea.SetWindowTitle` is available as a `Cmd` (also present in v1).
- The import for bubbles is `charm.land/bubbles/v2/...` and for lipgloss `charm.land/lipgloss/v2`.

Every pattern in this skill has a v2 equivalent; the Model/Update/View loop is unchanged. When in doubt, inspect the project's `go.mod` to see which major version is in use and match existing style.
