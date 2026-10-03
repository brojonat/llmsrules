# TODO

Status markers: `[ ]` open, `[x]` done, `[blocked: why]`.

- [ ] `mise run setup` (CPU) or `mise run setup:gpu` (CUDA), then `mise run skills`; commit the updated `skills-lock.json`
- [ ] `mise run check-gpu`, then `mise run up` (or `mise run loop`) on the simulated example; read `logs/sample.log` for compile time and fit time
- [ ] Your model: hand the dataset and problem description to an agent with the `new-model` skill (`.agents/skills/new-model/SKILL.md`): `prepare.sql`, `model.py`, `mise run check-model`, `bench --from`, then iterate in `mise run loop:cpu` / `loop`
- [ ] A live source instead of a file: write a feeder that keeps the contract (`obs` rows, then the `batches` marker with `n` and `coords`); `feed.replay` is the model
- [ ] Tune `--chains` / `--warmup` / `--draws` on the target GPU with `mise run bench`; check max R̂ on the dashboard
- [ ] Warm starts: start each fit from the previous fit's final positions and tuned step size to cut warmup
- [ ] Per-node explanations on hover over the model graph (generate with the description, cache in `model_notes`)
- [ ] `uv.lock` ships from the template with known-good PyMC/JAX/BlackJAX; `uv lock --upgrade` deliberately, then `mise run check-model` (compile.py leans on PyMC internals)
- [ ] Add a `plots` container to `k8s/prod/app.yaml` (same image, `args: ["plots"]`) so the deployed dashboard has figures
- [ ] Set the real domain in `k8s/prod/ingress.yaml`; create `.env.prod`; confirm the cluster has a GPU node with the NVIDIA device plugin
