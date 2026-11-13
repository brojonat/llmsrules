# TODO

- [ ] Replace the `items` example with this service's first real resource
- [ ] Set the ingress host in `k8s/prod/ingress.yaml`; create the `{{cookiecutter.project_slug}}-secrets` secret
- [ ] Database backups (Litestream to object storage, or a scheduled `VACUUM INTO` copy)
- [ ] CI: `mise run lint test`, then `docker build` on every push
- [ ] Compile-time checked queries (`query_as!` + a committed `.sqlx/` from `cargo sqlx prepare`) once the schema settles
- [ ] Run `./install-skills.sh` and commit `skills-lock.json`
