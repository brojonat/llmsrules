package todos

import (
	"fmt"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/starfederation/datastar-go/datastar"

	"{{cookiecutter.go_mod}}/internal/frames"
	"{{cookiecutter.go_mod}}/internal/httpx"
)

func handlePage(svc *Service, logger *slog.Logger, title string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Establish the session here so the stream and every mutation that
		// follows agree on which board they are talking about.
		if _, err := svc.EnsureSession(w, r); err != nil {
			logger.ErrorContext(r.Context(), "todos: ensure session", "error", err)
			httpx.WriteJSONError(w, "internal error", http.StatusInternalServerError)
			return
		}

		if err := Page(title).Render(r.Context(), w); err != nil {
			httpx.WriteJSONError(w, "render failed", http.StatusInternalServerError)
		}
	})
}

// handleStream is the read path: one long-lived SSE connection per browser tab.
//
// It never renders. It subscribes to this session's view on the frame renderer
// and sends whatever frame is newest, so a mutation from any source -- this
// tab, another tab, or a background job writing to the same key -- lands on
// screen the same way, at most one tick later.
func handleStream(svc *Service, renderer *frames.Renderer, logger *slog.Logger) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Must run before the SSE upgrade: it may set the session cookie, and
		// headers are flushed the moment the stream opens. It also seeds the
		// board, so the first render has something to read.
		sessionID, _, err := svc.Board(w, r)
		if err != nil {
			logger.ErrorContext(r.Context(), "todos: load board", "error", err)
			httpx.WriteJSONError(w, "internal error", http.StatusInternalServerError)
			return
		}

		sub, err := renderer.Subscribe(viewKey(sessionID))
		if err != nil {
			logger.ErrorContext(r.Context(), "todos: subscribe", "error", err)
			httpx.WriteJSONError(w, "internal error", http.StatusInternalServerError)
			return
		}
		defer sub.Close()

		sse := datastar.NewSSE(w, r, datastar.WithCompression())
		err = sub.Stream(r.Context(), func(html []byte) error {
			return sse.PatchElements(string(html))
		})
		if err != nil {
			// Normal on disconnect; the client reconnects on its own.
			logger.DebugContext(r.Context(), "todos: stream closed", "error", err)
		}
	})
}

// mutator changes a board in place. Returning an error aborts the save.
type mutator func(*Board, *http.Request) error

// handleMutate is the write path shared by every mutation route: load, apply,
// save. The response body stays empty on purpose -- the open SSE stream is
// what re-renders the UI.
func handleMutate(svc *Service, logger *slog.Logger, name string, apply mutator) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()

		sessionID, board, err := svc.Board(w, r)
		if err != nil {
			logger.ErrorContext(ctx, "todos: load board", "op", name, "error", err)
			httpx.WriteJSONError(w, "internal error", http.StatusInternalServerError)
			return
		}

		if err := apply(board, r); err != nil {
			httpx.WriteJSONError(w, err.Error(), http.StatusBadRequest)
			return
		}

		if err := svc.Save(ctx, sessionID, board); err != nil {
			logger.ErrorContext(ctx, "todos: save board", "op", name, "error", err)
			httpx.WriteJSONError(w, "internal error", http.StatusInternalServerError)
			return
		}

		w.WriteHeader(http.StatusNoContent)
	})
}

func reset(b *Board, _ *http.Request) error {
	b.Reset()
	return nil
}

func cancelEdit(b *Board, _ *http.Request) error {
	b.CancelEdit()
	return nil
}

func setMode(b *Board, r *http.Request) error {
	raw, err := pathInt(r, "mode")
	if err != nil {
		return err
	}
	mode := ViewMode(raw)
	if !mode.Valid() {
		return fmt.Errorf("unknown view mode %d", raw)
	}
	b.SetMode(mode)
	return nil
}

func toggle(b *Board, r *http.Request) error {
	idx, err := pathInt(r, "idx")
	if err != nil {
		return err
	}
	b.Toggle(idx)
	return nil
}

func startEdit(b *Board, r *http.Request) error {
	idx, err := pathInt(r, "idx")
	if err != nil {
		return err
	}
	b.StartEdit(idx)
	return nil
}

func saveEdit(b *Board, r *http.Request) error {
	idx, err := pathInt(r, "idx")
	if err != nil {
		return err
	}

	var signals struct {
		Input string `json:"input"`
	}
	if err := datastar.ReadSignals(r, &signals); err != nil {
		return fmt.Errorf("reading signals: %w", err)
	}
	if signals.Input == "" {
		b.CancelEdit()
		return nil
	}

	b.Edit(idx, signals.Input)
	return nil
}

func deleteTodo(b *Board, r *http.Request) error {
	idx, err := pathInt(r, "idx")
	if err != nil {
		return err
	}
	b.Delete(idx)
	return nil
}

func pathInt(r *http.Request, name string) (int, error) {
	v, err := strconv.Atoi(r.PathValue(name))
	if err != nil {
		return 0, fmt.Errorf("invalid %s: %w", name, err)
	}
	return v, nil
}
