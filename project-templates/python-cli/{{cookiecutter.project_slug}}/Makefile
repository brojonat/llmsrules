SHELL := /bin/bash

.PHONY: help
help: ## Show available targets
	@awk -F ':.*?## ' '/^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: install
install: ## Install dependencies
	uv sync

.PHONY: test
test: ## Run tests
	uv run pytest

.PHONY: lint
lint: ## Run linter
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

.PHONY: format
format: ## Format code
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

.PHONY: run
run: ## Run the CLI (pass ARGS="subcommand --flag")
	uv run {{cookiecutter.project_slug}} $(ARGS)

.PHONY: run-simple
run-simple: ## Run the simple PEP 723 script (pass ARGS="subcommand --flag")
	./simple.py $(ARGS)

.PHONY: clean
clean: ## Clean build artifacts
	rm -rf .venv/ __pycache__/ .pytest_cache/ .ruff_cache/ dist/ *.egg-info/
