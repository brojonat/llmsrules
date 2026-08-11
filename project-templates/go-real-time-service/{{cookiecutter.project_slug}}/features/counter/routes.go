package counter

import (
	"log/slog"
	"net/http"

	"github.com/gorilla/sessions"

	"{{cookiecutter.go_mod}}/internal/httpx"
)

func SetupRoutes(mux *http.ServeMux, logger *slog.Logger, store sessions.Store, adapters ...httpx.Adapter) error {
	counters := NewCounters(store)

	handle := func(pattern string, h http.Handler) {
		mux.Handle(pattern, httpx.Adapt(h, adapters...))
	}

	handle("GET /counter", handlePage("Counter"))
	handle("GET /counter/data", handleData(counters, logger))
	handle("POST /counter/increment/global", handleIncrementGlobal(counters, logger))
	handle("POST /counter/increment/user", handleIncrementUser(counters, logger))

	return nil
}
