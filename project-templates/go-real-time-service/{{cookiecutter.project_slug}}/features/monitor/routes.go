package monitor

import (
	"log/slog"
	"net/http"
	"time"

	"{{cookiecutter.go_mod}}/internal/frames"
	"{{cookiecutter.go_mod}}/internal/httpx"
)

const sampleInterval = 500 * time.Millisecond

func SetupRoutes(mux *http.ServeMux, logger *slog.Logger, renderer *frames.Renderer, adapters ...httpx.Adapter) error {
	// Nothing writes host stats, so nothing marks the view dirty. Every asks
	// the renderer to resample it on an interval while anyone is watching.
	renderer.Handle(viewKey, render, frames.Every(sampleInterval))

	mux.Handle("GET /monitor", httpx.Adapt(handlePage("System monitor"), adapters...))
	mux.Handle("GET /monitor/events", httpx.Adapt(handleEvents(renderer, logger), adapters...))
	return nil
}
