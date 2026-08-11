//go:build !prod

package resources

import (
	"log/slog"
	"net/http"
	"os"
)

// IsDev reports whether this binary was built for development. Templates use
// it to decide whether to wire up the live-reload listener.
const IsDev = true

func Handler() http.Handler {
	slog.Info("serving static assets from disk", "path", StaticDirectoryPath)
	fs := http.StripPrefix("/static/", http.FileServerFS(os.DirFS(StaticDirectoryPath)))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		fs.ServeHTTP(w, r)
	})
}

func StaticPath(path string) string {
	return "/static/" + path
}
