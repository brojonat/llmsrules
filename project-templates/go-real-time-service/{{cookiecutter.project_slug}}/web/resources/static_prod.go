//go:build prod

package resources

import (
	"embed"
	"log/slog"
	"net/http"

	"github.com/benbjohnson/hashfs"
)

const IsDev = false

// static must contain index.css and datastar/datastar.js at compile time.
// `mise run build` produces both (via the css and vendor tasks) before it
// compiles.
//
// The all: prefix keeps dotfiles in: without it a freshly generated tree
// holding only .gitkeep would fail to compile with "no matching files found".
//
//go:embed all:static
var static embed.FS

var staticSys = hashfs.NewFS(static)

func Handler() http.Handler {
	slog.Debug("serving embedded static assets")
	return hashfs.FileServer(staticSys)
}

// StaticPath returns a content-hashed URL so assets can be cached forever.
func StaticPath(path string) string {
	return "/" + staticSys.HashName("static/"+path)
}
