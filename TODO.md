
# TODO

- [x] Convert `project-templates/python-ducklake-service` frontend from HTMX to Datastar (live dashboard, Rocket d3 charts, debounced search); also wrote the missing `server/data/` layer, replaced MinIO with Garage, bound all SQL params, moved to mise.
- [x] Set the Brotli window in the Go Datastar templates and document the measurements in the datastar skill
- [x] Add `rust-datastar-minimal` (axum, maud, sqlx on SQLite, Brotli at a small window)
- [ ] Bring `rust-service` up to `go-service`: sqlx + SQLite with migrations, a thiserror `AppError` (anyhow in `main`), shared-state example, request IDs, latency histogram, then Dockerfile + k8s (its generated `TODO.md` has the list)
- [ ] Rust tick-based Datastar template, the counterpart of `go-real-time-service` (after `rust-datastar-minimal` has been used for real)
- [ ] `go-real-time-service`: commit `go.sum` so a generated project needs no `go mod tidy` (see LEARNINGS.md)
- [ ] Point the generated `rust-service` `AGENTS.md` at the rust skill's async references
