# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

### Changed

### Fixed

### Removed

## [0.1.0] - YYYY-MM-DD

### Added

- Initial release
- HTTP server on net/http ServeMux with graceful shutdown
- Embedded NATS JetStream broker with memory-backed KV buckets
- Tick-based frame renderer (`internal/frames`): views render once per tick
  per key, streams send the newest frame, overruns are logged and exported
- Datastar SSE patterns: per-session views, shared sampled views, signal
  patches
- templ views with computation kept in Go view structs
- Live reload in dev builds; embedded, content-hashed assets in prod builds
- mise as the front door (`mise tasks`), pinning Go and golangci-lint
- Vendored client libraries fetched by `scripts/vendor.sh` only when missing
- Health check and Prometheus metrics endpoints
- Structured JSON logging with slog
