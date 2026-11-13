module {{cookiecutter.go_mod}}

go 1.25.0

// Build tools are pinned here rather than installed globally, so `go tool
// templ` and `go tool gotailwind` work on a clean checkout (go.sum is committed).
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
	dario.cat/mergo v1.0.2 // indirect
	github.com/CAFxX/httpcompression v0.0.9 // indirect
	github.com/a-h/parse v0.0.0-20250122154542-74294addb73e // indirect
	github.com/air-verse/air v1.66.0 // indirect
	github.com/andybalholm/brotli v1.2.0 // indirect
	github.com/antithesishq/antithesis-sdk-go v0.7.2-default-no-op // indirect
	github.com/beorn7/perks v1.0.1 // indirect
	github.com/bep/godartsass/v2 v2.5.0 // indirect
	github.com/bep/golibsass v1.2.0 // indirect
	github.com/cenkalti/backoff v2.2.1+incompatible // indirect
	github.com/cenkalti/backoff/v4 v4.3.0 // indirect
	github.com/cespare/xxhash/v2 v2.3.0 // indirect
	github.com/cli/browser v1.3.0 // indirect
	github.com/cpuguy83/go-md2man/v2 v2.0.7 // indirect
	github.com/denisbrodbeck/machineid v1.0.1 // indirect
	github.com/ebitengine/purego v0.10.2 // indirect
	github.com/fatih/color v1.18.0 // indirect
	github.com/fsnotify/fsnotify v1.9.0 // indirect
	github.com/go-ole/go-ole v1.2.6 // indirect
	github.com/gobwas/glob v0.2.3 // indirect
	github.com/gohugoio/hugo v0.149.1 // indirect
	github.com/google/go-tpm v0.9.8 // indirect
	github.com/gorilla/securecookie v1.1.2 // indirect
	github.com/hookenz/gotailwind/v4 v4.3.2 // indirect
	github.com/joho/godotenv v1.5.1 // indirect
	github.com/klauspost/compress v1.19.1 // indirect
	github.com/klauspost/cpuid/v2 v2.3.0 // indirect
	github.com/lufia/plan9stats v0.0.0-20211012122336-39d0f177ccd0 // indirect
	github.com/mattn/go-colorable v0.1.14 // indirect
	github.com/mattn/go-isatty v0.0.20 // indirect
	github.com/minio/highwayhash v1.0.4 // indirect
	github.com/munnerz/goautoneg v0.0.0-20191010083416-a7dc8b61c822 // indirect
	github.com/natefinch/atomic v1.0.1 // indirect
	github.com/nats-io/jwt/v2 v2.8.2 // indirect
	github.com/nats-io/nkeys v0.4.16 // indirect
	github.com/nats-io/nuid v1.0.1 // indirect
	github.com/pelletier/go-toml v1.9.5 // indirect
	github.com/pelletier/go-toml/v2 v2.2.4 // indirect
	github.com/power-devops/perfstat v0.0.0-20240221224432-82ca36839d55 // indirect
	github.com/prometheus/client_model v0.6.2 // indirect
	github.com/prometheus/common v0.70.1 // indirect
	github.com/prometheus/procfs v0.21.1 // indirect
	github.com/russross/blackfriday/v2 v2.1.0 // indirect
	github.com/rzajac/zflake v0.8.1 // indirect
	github.com/spf13/afero v1.14.0 // indirect
	github.com/spf13/cast v1.9.2 // indirect
	github.com/tdewolff/parse/v2 v2.8.3 // indirect
	github.com/tklauser/go-sysconf v0.3.16 // indirect
	github.com/tklauser/numcpus v0.11.0 // indirect
	github.com/valyala/bytebufferpool v1.0.0 // indirect
	github.com/xrash/smetrics v0.0.0-20240521201337-686a1a2994c1 // indirect
	github.com/yusufpapurcu/wmi v1.2.4 // indirect
	github.com/zeebo/xxh3 v1.0.2 // indirect
	golang.org/x/crypto v0.54.0 // indirect
	golang.org/x/mod v0.37.0 // indirect
	golang.org/x/net v0.57.0 // indirect
	golang.org/x/sys v0.47.0 // indirect
	golang.org/x/text v0.40.0 // indirect
	golang.org/x/time v0.15.0 // indirect
	golang.org/x/tools v0.47.0 // indirect
	google.golang.org/protobuf v1.36.11 // indirect
)
