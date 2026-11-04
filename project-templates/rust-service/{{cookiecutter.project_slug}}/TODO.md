# TODO

This started as a stub of the `rust-service` template; these are the pieces
the Go and Python service templates have that this one doesn't yet.

- [ ] Dockerfile (cargo-chef for cached deps, static musl binary on a distroless or scratch base)
- [ ] K8s manifests with kustomize (`k8s/prod/`), plus `docker-build` / `deploy` mise tasks
- [ ] SQLite via sqlx (compile-time checked queries, migrations in `migrations/`)
- [ ] JWT auth as an extractor (`jsonwebtoken`), so `Claims` in a handler signature means "protected"
- [ ] Request IDs (`tower-http` request-id + propagate into the tracing span)
- [ ] Request duration histogram alongside the counter
- [ ] `install-skills.sh` matching the capabilities above
