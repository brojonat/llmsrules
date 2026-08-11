// Package resources serves the client-side assets.
//
// Two build tags select the strategy:
//
//	dev  (default) -- serve from disk, no caching, IsDev == true
//	prod           -- serve from an embedded FS with content-hashed names
//
// Build with `-tags=prod` for release binaries. `make build` does this for you.
package resources

const (
	StylesDirectoryPath = "web/resources/styles"
	StaticDirectoryPath = "web/resources/static"
)
