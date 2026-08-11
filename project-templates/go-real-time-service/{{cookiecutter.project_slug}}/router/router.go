// Package router assembles the feature slices into one mux.
//
// Each feature owns a SetupRoutes function and is joined here. Adding a
// feature is a single line plus a directory under features/.
package router

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"sync"

	"github.com/gorilla/sessions"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/starfederation/datastar-go/datastar"

	"{{cookiecutter.go_mod}}/features/counter"
	"{{cookiecutter.go_mod}}/features/monitor"
	"{{cookiecutter.go_mod}}/features/todos"
	"{{cookiecutter.go_mod}}/internal/broker"
	"{{cookiecutter.go_mod}}/internal/httpx"
	"{{cookiecutter.go_mod}}/web/resources"
)

type Deps struct {
	Logger   *slog.Logger
	Broker   *broker.Broker
	Sessions sessions.Store
	Registry *prometheus.Registry
}

func New(ctx context.Context, deps Deps) (http.Handler, error) {
	mux := http.NewServeMux()
	metrics := httpx.NewMetrics(deps.Registry)

	// Applied to every feature route. Order matters: outermost first.
	common := []httpx.Adapter{
		httpx.WithRequestID(),
		httpx.WithRecover(deps.Logger),
		httpx.WithLogging(deps.Logger),
		metrics.Adapter(),
	}

	mux.Handle("GET /healthz", httpx.Adapt(handleHealth(), httpx.WithRequestID()))
	mux.Handle("GET /metrics", promhttp.HandlerFor(deps.Registry, promhttp.HandlerOpts{}))
	mux.Handle("GET /static/", resources.Handler())

	if resources.IsDev {
		setupReload(mux, deps.Logger)
	}

	if err := errors.Join(
		todos.SetupRoutes(ctx, mux, deps.Logger, deps.Broker, deps.Sessions, common...),
		counter.SetupRoutes(mux, deps.Logger, deps.Sessions, common...),
		monitor.SetupRoutes(mux, deps.Logger, common...),
	); err != nil {
		return nil, fmt.Errorf("setting up feature routes: %w", err)
	}

	return mux, nil
}

func handleHealth() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		httpx.WriteJSON(w, map[string]string{"status": "ok"}, http.StatusOK)
	})
}

// setupReload gives dev builds browser live-reload without a browser extension.
//
// Every page holds a GET /reload open. air kills and restarts the binary on
// change, which drops those connections; Datastar reconnects, and the new
// process fires the once-per-boot reload that repaints the tab.
func setupReload(mux *http.ServeMux, logger *slog.Logger) {
	var once sync.Once

	mux.HandleFunc("GET /reload", func(w http.ResponseWriter, r *http.Request) {
		sse := datastar.NewSSE(w, r)
		once.Do(func() {
			if err := sse.ExecuteScript("window.location.reload()"); err != nil {
				logger.Debug("reload: client went away", "error", err)
			}
		})
		<-r.Context().Done()
	})
}
