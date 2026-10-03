# TODO

Status markers: `[ ]` open, `[x]` done, `[blocked: why]`.

- [ ] Replace `generate` with a fetch of the real source (keep the contract in README "Replacing it with real data")
- [ ] Reshape `schema.py`, `ingest.py` read models, `warehouse.DIMENSIONS` / `METRICS` and the templates for the real data
- [ ] Rewrite `docs/methodology.md` and `docs/assistant.md` for the real data; re-ask the tricky questions
- [ ] Replace `evals/cases.toml` with cases about the real data; run `mise run eval -- --repeat 3` for a baseline
- [ ] Decide what runs `deploy/refresh.sh` on a schedule (sidecar, CronJob + PVC, systemd timer)
- [ ] `uv lock` and commit `uv.lock` (the Dockerfile builds with `--frozen`)
- [ ] Run `./install-skills.sh` and commit `skills-lock.json`
- [ ] Set the real domain in `k8s/prod/ingress.yaml`; create `.env.prod` and `.env.admin`
