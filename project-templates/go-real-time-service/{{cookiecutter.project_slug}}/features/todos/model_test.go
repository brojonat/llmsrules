package todos

import "testing"

// NOTE: composite literals are written one element per line throughout this
// file. Collapsing them produces the character pair `{`+`{`, which cookiecutter
// parses as a Jinja expression when the template is generated.

func TestToggleAll(t *testing.T) {
	b := &Board{
		Todos: []Todo{
			{Text: "a"},
			{Text: "b", Completed: true},
		},
		EditingIdx: -1,
	}

	b.Toggle(-1) // not all complete -> complete everything
	for i, todo := range b.Todos {
		if !todo.Completed {
			t.Fatalf("todo %d should be completed", i)
		}
	}

	b.Toggle(-1) // all complete -> clear everything
	for i, todo := range b.Todos {
		if todo.Completed {
			t.Fatalf("todo %d should be active", i)
		}
	}
}

func TestDeleteCompleted(t *testing.T) {
	b := &Board{
		Todos: []Todo{
			{Text: "keep"},
			{Text: "drop", Completed: true},
		},
		EditingIdx: -1,
	}

	b.Delete(-1)

	if len(b.Todos) != 1 || b.Todos[0].Text != "keep" {
		t.Fatalf("expected only the active todo to survive, got %+v", b.Todos)
	}
}

func TestEditAppendsWhenIndexNegative(t *testing.T) {
	b := &Board{EditingIdx: 3}

	b.Edit(-1, "new item")

	if len(b.Todos) != 1 || b.Todos[0].Text != "new item" {
		t.Fatalf("expected the todo to be appended, got %+v", b.Todos)
	}
	if b.EditingIdx != -1 {
		t.Fatalf("editing should stop after an edit, got %d", b.EditingIdx)
	}
}

func TestViewFiltersByMode(t *testing.T) {
	b := &Board{
		Todos: []Todo{
			{Text: "a"},
			{Text: "b", Completed: true},
		},
		EditingIdx: -1,
		Mode:       ModeActive,
	}

	v := NewView(b)

	if len(v.Rows) != 1 || v.Rows[0].Text != "a" {
		t.Fatalf("expected only active todos, got %+v", v.Rows)
	}
	// Counts describe the whole board, not the filtered view.
	if v.Remaining != 1 || v.Completed != 1 {
		t.Fatalf("expected 1 remaining and 1 completed, got %d and %d", v.Remaining, v.Completed)
	}
}

func TestViewIndexesSurviveFiltering(t *testing.T) {
	b := &Board{
		Todos: []Todo{
			{Text: "done", Completed: true},
			{Text: "todo"},
		},
		EditingIdx: -1,
		Mode:       ModeActive,
	}

	v := NewView(b)

	// The row must carry its board index, not its position in the filtered
	// slice, or the mutation routes would target the wrong todo.
	if len(v.Rows) != 1 || v.Rows[0].Idx != 1 {
		t.Fatalf("filtered row must keep board index 1, got %+v", v.Rows)
	}
}
