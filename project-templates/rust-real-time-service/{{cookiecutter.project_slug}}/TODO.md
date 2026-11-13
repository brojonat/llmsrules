# TODO

- [ ] Replace the demo features with this service's first real view (keep `todos.rs` as the pattern)
- [ ] Real auth before storing anything that matters (the session cookie is an id, not a login)
- [ ] Set the ingress host in `k8s/prod/ingress.yaml`
- [ ] Database backups (Litestream to object storage, or a scheduled `VACUUM INTO` copy)
- [ ] Vendor `datastar.js` instead of loading it from the CDN, if the app must work offline
- [ ] CI: `mise run lint test`, then `docker build` on every push
- [ ] Run `./install-skills.sh` and commit `skills-lock.json`
