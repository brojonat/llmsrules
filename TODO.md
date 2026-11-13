
# TODO

- [x] Convert `project-templates/python-ducklake-service` frontend from HTMX to Datastar (live dashboard, Rocket d3 charts, debounced search); also wrote the missing `server/data/` layer, replaced MinIO with Garage, bound all SQL params, moved to mise.
- [x] Set the Brotli window in the Go Datastar templates and document the measurements in the datastar skill
- [x] Add `rust-datastar-minimal` (axum, maud, sqlx on SQLite, Brotli at a small window)
- [x] Bring `rust-service` up to `go-service`: sqlx + SQLite with migrations, a thiserror `AppError` (anyhow in `main`), JWT auth, request IDs, latency histogram, Dockerfile + k8s + deploy script
- [x] Add `rust-real-time-service`, the Rust counterpart of `go-real-time-service` (tick renderer on `watch` channels, Brotli quality 1, load-test task)
- [x] `go-real-time-service`: commit `go.sum`; setup runs `go mod download` instead of `go mod tidy`
- [x] Point the generated `rust-service` `AGENTS.md` at the rust skill's async references
- [ ] Use `rust-real-time-service` for a real project, then fold what it teaches back into the template and the datastar skill
- [ ] Go templates: measure Brotli quality 1 vs 6 per stream under load and decide whether to change the default (Go gains about 2x memory for about 2x bytes, less than Rust)
- [ ] Convert the Makefile templates (`go-service`, `go-local-app`, `python-service`, `python-cli`) to mise
