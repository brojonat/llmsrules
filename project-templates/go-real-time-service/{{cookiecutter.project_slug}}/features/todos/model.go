package todos

// Board is the persisted state for one session. It is stored as JSON in a
// JetStream KV bucket keyed by session ID.
//
// Mutating methods take an index; a negative index means "all todos", which is
// how the toggle-all and clear-completed buttons are expressed.
type Board struct {
	Todos      []Todo   `json:"todos"`
	EditingIdx int      `json:"editingIdx"`
	Mode       ViewMode `json:"mode"`
}

type Todo struct {
	Text      string `json:"text"`
	Completed bool   `json:"completed"`
}

type ViewMode int

const (
	ModeAll ViewMode = iota
	ModeActive
	ModeCompleted
	modeCount
)

var modeNames = [modeCount]string{"All", "Active", "Completed"}

func (m ViewMode) Valid() bool { return m >= ModeAll && m < modeCount }

func (m ViewMode) String() string {
	if !m.Valid() {
		return "All"
	}
	return modeNames[m]
}

// NewBoard returns a board seeded with example todos.
func NewBoard() *Board {
	b := &Board{}
	b.Reset()
	return b
}

func (b *Board) Reset() {
	b.Mode = ModeAll
	b.EditingIdx = -1
	b.Todos = []Todo{
		{Text: "Wire this service into a data stream", Completed: false},
		{Text: "Delete the demo features", Completed: false},
		{Text: "Ship it", Completed: false},
	}
}

// Toggle flips one todo. A negative index sets every todo to completed unless
// they already all are, in which case it clears them.
func (b *Board) Toggle(idx int) {
	if idx >= 0 {
		if idx < len(b.Todos) {
			b.Todos[idx].Completed = !b.Todos[idx].Completed
		}
		return
	}

	target := false
	for _, t := range b.Todos {
		if !t.Completed {
			target = true
			break
		}
	}
	for i := range b.Todos {
		b.Todos[i].Completed = target
	}
}

// Edit replaces the text of one todo, or appends a new one when idx is
// negative. Either way editing stops.
func (b *Board) Edit(idx int, text string) {
	if idx >= 0 && idx < len(b.Todos) {
		b.Todos[idx].Text = text
	} else if idx < 0 {
		b.Todos = append(b.Todos, Todo{Text: text})
	}
	b.EditingIdx = -1
}

// Delete removes one todo, or every completed todo when idx is negative.
func (b *Board) Delete(idx int) {
	if idx >= 0 {
		if idx < len(b.Todos) {
			b.Todos = append(b.Todos[:idx], b.Todos[idx+1:]...)
		}
		b.EditingIdx = -1
		return
	}

	kept := b.Todos[:0]
	for _, t := range b.Todos {
		if !t.Completed {
			kept = append(kept, t)
		}
	}
	b.Todos = kept
	b.EditingIdx = -1
}

func (b *Board) StartEdit(idx int)     { b.EditingIdx = idx }
func (b *Board) CancelEdit()           { b.EditingIdx = -1 }
func (b *Board) SetMode(mode ViewMode) { b.Mode = mode }
