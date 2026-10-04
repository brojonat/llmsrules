# TODO

Status markers: `[ ]` open, `[x]` done, `[blocked: why]`.

- [ ] `mise run setup` (CPU) or `mise run setup:gpu` (CUDA), then `mise run skills`; commit the updated `skills-lock.json`
- [ ] On the simulated example: `mise run simulate`, `mise run loop:cpu` (or `check-gpu`, then `loop`), `mise run feed --chunk 1000`; read `logs/sample.log` for compile time and fit time
- [ ] Your model: hand the dataset and problem description to an agent with the `new-model` skill (`.agents/skills/new-model/SKILL.md`): `prepare.sql`, `model.py`, `mise run check-model`, `bench --from`, then iterate in `mise run loop:cpu` / `loop`, feeding the data the way you ask
- [ ] A live source instead of a file: a feeder that keeps the contract (a `runs` row with the labels, then per batch its `obs` rows and the `batches` marker); `feed.run` is the model
- [ ] Tune `--chains` / `--warmup` / `--draws` on the target GPU with `mise run bench`; check max R̂ on the dashboard
- [ ] Warm starts: start each fit from the previous fit's final positions and tuned step size to cut warmup
- [ ] Per-node explanations on hover over the model graph (generate with the description, cache in `model_notes`)
- [ ] `uv.lock` ships from the template with known-good PyMC/JAX/BlackJAX; `uv lock --upgrade` deliberately, then `mise run check-model` (compile.py leans on PyMC internals)
