package todos

import (
	"context"
	"log/slog"
	"net/http"

	"github.com/gorilla/sessions"

	"{{cookiecutter.go_mod}}/internal/broker"
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
	adapters ...httpx.Adapter,
) error {
	svc, err := NewService(ctx, b, store)
	if err != nil {
		return err
	}

	handle := func(pattern string, h http.Handler) {
		mux.Handle(pattern, httpx.Adapt(h, adapters...))
	}

	handle("GET /{$}", handlePage(svc, logger, "Todos"))
	handle("GET /api/todos", handleStream(svc, logger))

	handle("PUT /api/todos/reset", handleMutate(svc, logger, "reset", reset))
	handle("PUT /api/todos/cancel", handleMutate(svc, logger, "cancel", cancelEdit))
	handle("PUT /api/todos/mode/{mode}", handleMutate(svc, logger, "mode", setMode))

	handle("POST /api/todos/item/{idx}/toggle", handleMutate(svc, logger, "toggle", toggle))
	handle("GET /api/todos/item/{idx}/edit", handleMutate(svc, logger, "start-edit", startEdit))
	handle("PUT /api/todos/item/{idx}/edit", handleMutate(svc, logger, "save-edit", saveEdit))
	handle("DELETE /api/todos/item/{idx}", handleMutate(svc, logger, "delete", deleteTodo))

	return nil
}
