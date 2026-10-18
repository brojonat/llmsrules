package todos

import (
	"context"
	"log/slog"
	"net/http"

	"github.com/gorilla/sessions"

	"{{cookiecutter.go_mod}}/internal/broker"
	"{{cookiecutter.go_mod}}/internal/frames"
	"{{cookiecutter.go_mod}}/internal/httpx"
)

// SetupRoutes wires the todos feature onto mux.
//
// Note the /item/ segment on the per-todo routes. Without it,
// "PUT /api/todos/mode/{mode}" and "PUT /api/todos/{idx}/edit" would both
// match "/api/todos/mode/edit" with neither being more specific, and
// net/http's ServeMux panics on that ambiguity at registration time.
func SetupRoutes(
	ctx context.Context,
	mux *http.ServeMux,
	logger *slog.Logger,
	b *broker.Broker,
	store sessions.Store,
	renderer *frames.Renderer,
	adapters ...httpx.Adapter,
) error {
	svc, err := NewService(ctx, b, store)
	if err != nil {
		return err
	}

	// Each session's board is one view, keyed "todos/<session id>". Two tabs on
	// the same session share one render per tick.
	renderer.Handle(viewPrefix, svc.Render)

	// Every write to the bucket marks that session's view dirty, whoever made
	// it: a mutation route, another replica's tab, or a background job. The
	// watcher stops when ctx is cancelled at shutdown.
	if err := svc.MarkDirtyOnWrite(ctx, renderer, logger); err != nil {
		return err
	}

	handle := func(pattern string, h http.Handler) {
		mux.Handle(pattern, httpx.Adapt(h, adapters...))
	}

	handle("GET /{$}", handlePage(svc, logger, "Todos"))
	handle("GET /api/todos", handleStream(svc, renderer, logger))

	handle("PUT /api/todos/reset", handleMutate(svc, logger, "reset", reset))
	handle("PUT /api/todos/cancel", handleMutate(svc, logger, "cancel", cancelEdit))
	handle("PUT /api/todos/mode/{mode}", handleMutate(svc, logger, "mode", setMode))

	handle("POST /api/todos/item/{idx}/toggle", handleMutate(svc, logger, "toggle", toggle))
	handle("GET /api/todos/item/{idx}/edit", handleMutate(svc, logger, "start-edit", startEdit))
	handle("PUT /api/todos/item/{idx}/edit", handleMutate(svc, logger, "save-edit", saveEdit))
	handle("DELETE /api/todos/item/{idx}", handleMutate(svc, logger, "delete", deleteTodo))

	return nil
}
