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

- FastAPI server with DuckLake integration
- Generic events table for analytics data
- Magic link email authentication
- Session management with cookie-based auth
- PostgreSQL app database for users, sessions, tags
- Tag CRUD and entity tagging API
- Datastar frontend with dark/light theme: live dashboard over one SSE
  stream (re-rendered once per lake snapshot), debounced entity search,
  entity pages
- d3 charts as Datastar Rocket web components
- `POST /api/events` to append events to the lake
- Click CLI: serve, migrate, lake admin, app admin
- Prometheus metrics and structured logging
- Docker Compose for local dev (Postgres + SeaweedFS as S3)
- mise as the front door (`mise tasks`)
- Kubernetes manifests (Kustomize)
- Migration system with namespace isolation
