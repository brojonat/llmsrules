# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); newest first.

## [Unreleased]

### Added
- Generated from the `python-bayes-loop` template: a PyMC hierarchical
  logistic regression lowered to JAX with data as arguments, compile-once
  BlackJAX ChEES and NUTS samplers with on-device summaries, a DuckDB belt
  served over Quack (`db`, `feed`, `sample`), labeled dims and coords end to
  end, a Datastar dashboard with d3 Rocket charts driven by the model's
  `VIEW`, the model graph rendered in the browser with an LLM-written
  description, `/healthz` and `/metrics`, GPU and CPU mise profiles,
  benchmarks, and a one-pod Kubernetes deployment.
- The model contract (`model.py`, checked by `mise run check-model`), file
  replay (`feed --from`, `bench --from`), the tmux loop (`mise run loop`,
  `sample --refit`), and the `new-model` agent skill with the PyMC Labs
  skills from Decision Hub (`install-skills.sh`).
