# llmsrules

This is a repo for storing the dotfiles I use for various LLM based agents (Cursor, Claude, Goose, etc). Each agent seems to take a slightly different format; each provider has a separate folder here. I treat this kind of like notes when I'm reading over a new API, so it's multipurpose.

The `.cursorrules` is the prototypical example. Cursor-specific rules live under `.cursor/rules/` and use `.mdc` files with front‑matter (description, globs, alwaysApply) plus guidance content.

## What’s here

- Cursor rules: [`.cursor/rules/`](.cursor/rules)
  - [`fastapi.mdc`](.cursor/rules/fastapi.mdc): Minimal FastAPI server with JWT auth, Prometheus, and structlog
  - [`project-layout.mdc`](.cursor/rules/project-layout.mdc): Opinionated project skeleton (CLI, server, notebooks, assets)
  - [`python-cli.mdc`](.cursor/rules/python-cli.mdc): Scaffold and structure Python Click CLIs
  - [`pyproject.mdc`](.cursor/rules/pyproject.mdc): What to include in `pyproject.toml` (scripts, ruff, pytest, src layout)
  - [`scikit-learn.mdc`](.cursor/rules/scikit-learn.mdc): Practical sklearn pipelines, tuning, metrics, persistence, MLflow

## Using these rules in a project (Cursor)

1. Copy or reference the files under `.cursor/rules/` into your project’s `.cursor/rules/` directory.
2. Adjust each rule’s `globs` to match the files you want it to apply to. Most Python rules here already target `**/*.py` (and notebooks where relevant).
3. Leave `alwaysApply: false` unless you want a rule to be applied all the time.

Rules are additive: keep focused guidance per rule (e.g., server, CLI, data science) and let Cursor use the glob patterns to surface the right guidance at the right time.

## Conventions

- Keep rules small and purpose-built; prefer multiple focused `.mdc` files over a single monolith.
- Use clear `description` text and conservative `globs`.
- Where relevant, include minimal quickstart snippets and env var names expected by the code (e.g., `AUTH_SECRET` for FastAPI auth).

## Using these rules in a project (Claude)

1. `cat` or copy or reference snippets from the files under `claude/` into your project’s `CLAUDE.md` file.
2. Tweak the file to your project's needs.
