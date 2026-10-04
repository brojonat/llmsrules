# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); newest first.

## [Unreleased]

### Added
- Generated from the `python-bayes-loop` template: a PyMC hierarchical
  logistic regression lowered to JAX with data as arguments, compile-once
  BlackJAX ChEES and NUTS samplers with on-device summaries, a DuckDB belt
  served over Quack (`db`, `sample`, `plots`, `serve`), labeled dims and
  coords end to end, a read-only Datastar dashboard with d3 Rocket charts
  driven by the model's `VIEW`, the model graph rendered in the browser,
  figures (predictive checks, traces, prior vs posterior, rank plots),
  `/healthz` and `/metrics`, GPU and CPU mise profiles, and benchmarks.
- Feeding data through a cursor (`feed --rows N|P%`, `--chunk N`,
  `--restart`), every fit on all rows fed so far, row padding so fits share
  compiled programs, and `simulate` for a dataset with known truth.
- The model contract (`model.py`, checked by `mise run check-model`), the
  tmux loop (`mise run loop`), the agent's journal on the dashboard (`note`,
  `status`, `describe`, `figure`), and the `new-model` agent skill with the
  PyMC Labs skills from Decision Hub (`install-skills.sh`).
