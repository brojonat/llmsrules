module {{cookiecutter.go_mod}}

go 1.25.0

// Build tools are pinned here rather than installed globally, so `go tool
// templ` and `go tool gotailwind` work on a clean checkout after `go mod tidy`.
tool (
	github.com/a-h/templ/cmd/templ
	github.com/air-verse/air
	github.com/hookenz/gotailwind/v4
)

require (
	github.com/a-h/templ v0.3.1020
	github.com/benbjohnson/hashfs v0.2.2
	github.com/delaneyj/toolbelt v0.9.1
	github.com/dustin/go-humanize v1.0.1
	github.com/golang-jwt/jwt/v5 v5.3.1
	github.com/gorilla/sessions v1.4.0
	github.com/nats-io/nats-server/v2 v2.14.4
	github.com/nats-io/nats.go v1.52.0
	github.com/prometheus/client_golang v1.24.1
	github.com/shirou/gopsutil/v4 v4.26.7
	github.com/starfederation/datastar-go v1.2.2
	github.com/urfave/cli/v2 v2.27.7
	golang.org/x/sync v0.22.0
)

require (
	github.com/air-verse/air v1.66.0 // indirect
	github.com/hookenz/gotailwind/v4 v4.3.2 // indirect
)
