SHELL := /bin/bash

define setup_env
	$(eval ENV_FILE := $(1))
	$(eval include $(1))
	$(eval export)
endef

.PHONY: help
help: ## Show available targets
	@awk -F ':.*?## ' '/^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: install
install: ## Install dependencies (including dev)
	uv sync --all-extras

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

.PHONY: run-server
run-server: ## Run the FastAPI server
	$(call setup_env, .env.server)
	uv run uvicorn {{cookiecutter.package_name}}.server.main:app --host 0.0.0.0 --port 8000 --reload

.PHONY: run-mlflow
run-mlflow: ## Run the MLflow UI server
	$(call setup_env, .env.server)
	uv run mlflow ui \
		--backend-store-uri $${MLFLOW_TRACKING_URI:-mlflow.db} \
		--host 127.0.0.1 \
		--port 5000

.PHONY: start-dev
start-dev: ## Start tmux dev session with API server and MLflow UI
	@tmux new-session -d -s {{cookiecutter.project_slug}} -n mlflow
	@tmux send-keys -t {{cookiecutter.project_slug}}:mlflow 'make run-mlflow' C-m
	@tmux new-window -t {{cookiecutter.project_slug}} -n api
	@tmux send-keys -t {{cookiecutter.project_slug}}:api 'make run-server' C-m
	@echo "Dev session '{{cookiecutter.project_slug}}' started."
	@echo "MLflow UI running in window 'mlflow' (port 5000)"
	@echo "API server running in window 'api' (port 8000)"
	@echo "Attach with: tmux attach -t {{cookiecutter.project_slug}}"

.PHONY: stop-dev
stop-dev: ## Stop the tmux dev session
	@tmux kill-session -t {{cookiecutter.project_slug}} || true

.PHONY: docker-up
docker-up: ## Start docker-compose services
	docker-compose up -d

.PHONY: docker-down
docker-down: ## Stop docker-compose services
	docker-compose down

.PHONY: clean
clean: ## Clean build artifacts
	rm -rf .venv/ __pycache__/ .pytest_cache/ .ruff_cache/ dist/ *.egg-info/ mlruns/ mlflow.db
