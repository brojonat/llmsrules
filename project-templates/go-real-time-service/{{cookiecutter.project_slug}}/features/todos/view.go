package todos

import (
	"encoding/json"
	"fmt"

	"github.com/starfederation/datastar-go/datastar"
)

// View is everything the template needs, precomputed.
//
// Templates stay declarative on purpose: no loops that count, no conditionals
// that derive state, no formatting. If a template needs a value, compute it
// here where it can be unit tested.
type View struct {
	Rows      []Row
	Modes     []ModeTab
	HasTodos  bool
	Remaining int
	Completed int
	ItemsWord string
	Editing   bool
	Input     string
}

type Row struct {
	Idx       int
	Text      string
	Completed bool
	Editing   bool
	Signal    string // per-row Datastar signal name for the in-flight indicator
}

type ModeTab struct {
	Mode     ViewMode
	Name     string
	Selected bool
}

// NewView projects a Board into its renderable form, applying the mode filter.
func NewView(b *Board) View {
	v := View{
		HasTodos:  len(b.Todos) > 0,
		Editing:   b.EditingIdx >= 0,
		ItemsWord: "items",
	}

	for i, t := range b.Todos {
		if t.Completed {
			v.Completed++
		} else {
			v.Remaining++
		}

		if !visible(b.Mode, t) {
			continue
		}
		v.Rows = append(v.Rows, Row{
			Idx:       i,
			Text:      t.Text,
			Completed: t.Completed,
			Editing:   i == b.EditingIdx,
			Signal:    fmt.Sprintf("busy%d", i),
		})
	}

	if v.Remaining == 1 {
		v.ItemsWord = "item"
	}

	if b.EditingIdx >= 0 && b.EditingIdx < len(b.Todos) {
		v.Input = b.Todos[b.EditingIdx].Text
	}

	for m := ModeAll; m < modeCount; m++ {
		v.Modes = append(v.Modes, ModeTab{Mode: m, Name: m.String(), Selected: m == b.Mode})
	}

	return v
}

func visible(mode ViewMode, t Todo) bool {
	switch mode {
	case ModeActive:
		return !t.Completed
	case ModeCompleted:
		return t.Completed
	default:
		return true
	}
}

// EditingIdx is the index the input field posts to: the row being edited, or
// -1 to append a new todo.
func (v View) EditingIdx() int {
	for _, r := range v.Rows {
		if r.Editing {
			return r.Idx
		}
	}
	return -1
}

// inputSignal renders the initial Datastar signal payload for the text input.
// Going through encoding/json keeps quotes and backslashes in todo text from
// breaking out of the attribute.
func inputSignal(input string) string {
	b, err := json.Marshal(map[string]string{"input": input})
	if err != nil {
		return `{"input":""}`
	}
	return string(b)
}

// submitOnEnter is the keydown expression for the todo input: ignore anything
// that is not Enter, ignore whitespace-only input, otherwise save and clear.
func submitOnEnter(idx int) string {
	return fmt.Sprintf(
		"if (evt.key !== 'Enter' || !$input.trim().length) return; %s; $input = ''",
		datastar.PutSSE("/api/todos/item/%d/edit", idx),
	)
}
