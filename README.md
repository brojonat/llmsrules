# llmsrules

This started as a repo for storing the dotfiles I use for various LLM based
agents (Cursor, Claude, Goose, etc). Each agent seems to take a slightly
different format, so each provider has a separate folder here. I'll typically
use an agent to port the documents from one provider to another.

The `.cursorrules` is the prototypical example. Cursor-specific rules live under
`.cursor/rules/` and use `.mdc` files with front‑matter (description, globs,
alwaysApply) plus guidance content. This format differs from the vanilla `.md`
and Skills files I have in the Claude directory. You get the idea.

However, I quickly realized I was going about this all wrong. See, about a
decade ago I had this dream of having a library of project templates that I
could use to bootstrap new projects and get cracking in the blink of an eye. I
think it might have been @tiangolo's
[full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template)
that awared me on [Cookiecutter](https://github.com/cookiecutter/cookiecutter),
but in the end my poor hands were not up to the task of writing all the
necessary {{ template }} code that would be necessary to realize my vision.

Today, things are different. Now we have agents. A lot of people are focusing on
writing markdown files, for their Rules, Skills, etc., and that's all well and
good. Remember though, all you want some boilerplate code laying out your
project. Instead of trying to prompt and coax your agent into writing something
that _mostly somewhat closely resembles_ the end product you want and then
having to clean it up after the fact, just give it a template of the thing!

So, instead of having your agent write style guidelines, just spend a few hours
and have an agent hammer out templates of your boilerplate project styles and be
done with it.

Here's the main selling points:

- Zero cost, immediate project bootstrapping.
- Same patterns and entry points across all your projects.
- Templates are deterministic; no subtle differences based on the whims of the
  agent.
- Templates play nicely with version control.

That's what's in the `project-templates` directory: starter templates for how I
like to structure my projects.

## Templates

| Template | Description | Key Features |
|----------|-------------|--------------|
| `go-service` | Go microservice | stdlib HTTP handlers, urfave/cli, sqlc, slog, Air hot reload |
| `python-service` | Python microservice | FastAPI, Click CLI, uv, structlog, Prometheus metrics |
| `python-cli` | Python CLI tool | PEP 723 simple script + structured package with subcommands |

All templates include: Makefile, Dockerfile, K8s manifests, `.gitignore`, `AGENTS.md`, `CHANGELOG.md`.

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

See [`project-templates/README.md`](project-templates/README.md) for full documentation.
