# llmsrules

This started as a repo for storing the dotfiles I used for various LLM-based
agents (Cursor, Claude, Goose, etc). Each agent took a slightly different
format, so I maintained a separate folder per provider and ported documents
between them.

That approach collapsed once the [Agent Skills
spec](https://agentskills.io) and [skills.sh](https://skills.sh/) landed. A
single `SKILL.md` format now works across 40+ agents, so everything I maintain
lives in `skills/` and gets distributed via `npx skills add`. `AGENTS.md`
captures the high-level philosophy that applies to every project I bootstrap.

I also realized I was going about this all wrong. See, about a
decade ago I had this dream of having a library of project templates that I
could use to bootstrap new projects and get cracking in the blink of an eye. I
think it might have been @tiangolo's
[full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template)
that awared me on [Cookiecutter](https://github.com/cookiecutter/cookiecutter),
but in the end my poor hands were not up to the task of writing all the
necessary {{ template }} code that would be necessary to realize my vision.

Today, things are different. Now we have agents. A lot of people are focusing on
writing markdown files for their Rules, Skills, etc., and that's all well and
good and certainly has it's place. Remember though, I'm just after some
boilerplate code for laying out some projects. Instead of trying to prompt and
coax an agent into writing something that _mostly somewhat closely resembles_
the end product I want and then having to perform tedious tweaking after the
fact, I can just give it a template of the thing!

So, instead of having an agent write style guidelines, I've just spent that time
having an agent hammer out templates of my boilerplate project styles. Here's
the main selling points:

- Zero cost, immediate project bootstrapping.
- Same patterns and entry points across all your projects.
- Templates are deterministic; no subtle differences based on the whims of the
  agent.
- Templates play nicely with version control.

That's what's in the `project-templates` directory: starter templates for how I
like to structure my projects.

## Templates

| Template         | Description         | Key Features                                                 |
| ---------------- | ------------------- | ------------------------------------------------------------ |
| `go-service`     | Go microservice     | stdlib HTTP handlers, urfave/cli, sqlc, slog, Air hot reload |
| `python-service` | Python microservice | FastAPI, Click CLI, uv, structlog, Prometheus metrics        |
| `python-cli`     | Python CLI tool     | PEP 723 simple script + structured package with subcommands  |

All templates include: Makefile, Dockerfile, K8s manifests, `.gitignore`,
`AGENTS.md`, `CHANGELOG.md`.

```bash
# Install cookiecutter
uv tool install cookiecutter

# Create a project
cookiecutter project-templates/go-service
cookiecutter project-templates/python-service
cookiecutter project-templates/python-cli

# Validate templates
./project-templates/test-templates.py validate
```

See [`project-templates/README.md`](project-templates/README.md) for full
documentation.

## Skills

I use [skills.sh](https://skills.sh/) to manage reusable agent skills. Skills
are packages of instructions, scripts, and resources that AI coding agents load
dynamically — think plugins for your agent. They follow the open
[Agent Skills spec](https://agentskills.io) and work across 40+ agents (Claude
Code, Cursor, Copilot, Gemini CLI, etc.).

### Managing skills with `npx skills`

```bash
# Find skills interactively or by keyword
npx skills find
npx skills find "bayesian"

# List available skills in a repo before installing
npx skills add <owner/repo> --list

# Install skills (symlinked by default, easy to update)
npx skills add <owner/repo>                    # all skills, project-local
npx skills add <owner/repo> -g                 # install globally (~/)
npx skills add <owner/repo> -s skill-name      # specific skill only
npx skills add <owner/repo> -a claude-code     # target a specific agent

# Check for updates and apply them
npx skills check
npx skills update

# List and remove installed skills
npx skills list
npx skills remove <skill-name>

# Scaffold a new skill
npx skills init my-skill
```

### Installing all skills

To install everything (my skills + all third-party skills listed below) into a
project, run from that project's root:

```bash
./install-skills.sh
```

This populates a `skills-lock.json` you can commit. On another machine, restore
the same set with:

```bash
npx skills experimental_install
```

### Skills in this repo

These are my own skills, extracted from the docs in this repo. Install them into
any project with:

```bash
npx skills add brojonat/llmsrules
```

| Skill              | Description                                                         |
| ------------------ | ------------------------------------------------------------------- |
| `fastapi-service`  | FastAPI with JWT auth, structlog, Prometheus metrics                |
| `python-cli`       | Click CLI with composable subcommand groups                         |
| `go-service`       | Go microservice with stdlib HTTP, sqlc, urfave/cli, slog            |
| `scikit-learn`     | ML pipelines, cross-validation, hyperparameter tuning, MLflow       |
| `k8s-deployment`   | Docker multi-stage builds, kustomize overlays, Makefile automation  |
| `ducklake`         | DuckLake lakehouse: snapshots, time travel, schema evolution        |
| `openai-agents`    | OpenAI Agents SDK: tools, handoffs, context, webhooks (Python + Go) |
| `pyproject-config` | pyproject.toml with setuptools, ruff, pytest                        |
| `ibis-data`        | Database-agnostic data access with Ibis                             |
| `parquet-analysis` | Parquet file analysis with Ibis and DuckDB                          |
| `temporal-go`      | Temporal workflows, activities, workers, signals, sagas in Go       |
| `temporal-python`  | Temporal workflows, activities, workers, signals, sagas in Python   |

### Third-party skills I like

| Repository                                                              | Focus                     | Highlights                                                                                        |
| ----------------------------------------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------- |
| [anthropics/skills](https://github.com/anthropics/skills)               | Anthropic official        | `frontend-design`, `pdf`, `docx`, `xlsx`, `pptx`, `skill-creator`                                 |
| [obra/superpowers](https://github.com/obra/superpowers)                 | Dev methodology           | `systematic-debugging`, `test-driven-development`, `dispatching-parallel-agents`, `writing-plans` |
| [pymc-labs/agent-skills](https://github.com/pymc-labs/agent-skills)     | Probabilistic programming | `pymc-modeling` (Bayesian stats, PyMC v5+, ArviZ, BART), `marimo-notebooks`                       |
| [marimo-team/skills](https://github.com/marimo-team/skills)             | marimo notebooks          | `marimo-notebook`, `jupyter-to-marimo`, `streamlit-to-marimo`, `anywidget`, `implement-paper`     |
| [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | React / Next.js           | `vercel-react-best-practices`, `web-design-guidelines`, `deploy-to-vercel`                        |
| [supabase/agent-skills](https://github.com/supabase/agent-skills)       | PostgreSQL                | `supabase-postgres-best-practices`                                                                |
| [temporalio/skill-temporal-developer](https://github.com/temporalio/skill-temporal-developer) | Temporal                  | Official Temporal developer skill                                                                 |
| [planetscale/database-skills](https://github.com/planetscale/database-skills) | MySQL / PlanetScale       | PlanetScale database development skills                                                           |
