package monitor

import (
	"log/slog"
	"net/http"
	"time"

	"{{cookiecutter.go_mod}}/internal/httpx"
)

const sampleInterval = 500 * time.Millisecond

func SetupRoutes(mux *http.ServeMux, logger *slog.Logger, adapters ...httpx.Adapter) error {
	mux.Handle("GET /monitor", httpx.Adapt(handlePage("System monitor"), adapters...))
	mux.Handle("GET /monitor/events", httpx.Adapt(handleEvents(logger, sampleInterval), adapters...))
	return nil
}
