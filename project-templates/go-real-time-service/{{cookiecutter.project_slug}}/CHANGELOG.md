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
- Datastar SSE patterns: KV-watch fragments, server push, signal patches
- templ views with computation kept in Go view structs
- Live reload in dev builds; embedded, content-hashed assets in prod builds
- Vendored client libraries as Make file targets, fetched only when missing
- Health check and Prometheus metrics endpoints
- Structured JSON logging with slog
