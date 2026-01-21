SHELL := /bin/bash

define setup_env
	$(eval ENV_FILE := $(1))
	$(eval include $(1))
	$(eval export)
endef

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
	uv run ruff check src/ server/ tests/
	uv run ruff format --check src/ server/ tests/

.PHONY: format
format: ## Format code
	uv run ruff format src/ server/ tests/
	uv run ruff check --fix src/ server/ tests/

.PHONY: run-dev
run-dev: ## Run server with auto-reload (logs to logs/)
	@mkdir -p logs
	$(call setup_env, .env.server)
	uv run uvicorn server.main:app --reload --host 0.0.0.0 --port 8000 2>&1 | tee logs/server.log

.PHONY: run
run: ## Run production server
	$(call setup_env, .env.server)
	uv run uvicorn server.main:app --host 0.0.0.0 --port 8000

.PHONY: clean
clean: ## Clean build artifacts
	rm -rf .venv/ __pycache__/ .pytest_cache/ .ruff_cache/ logs/*.log dist/ *.egg-info/

.PHONY: deploy
deploy: ## Build, push, and deploy to Kubernetes
	$(call setup_env, .env.prod)
	$(eval GIT_HASH := $(shell git rev-parse --short HEAD))
	docker build -t $(DOCKER_REGISTRY)/{{cookiecutter.project_slug}}:$(GIT_HASH) .
	docker push $(DOCKER_REGISTRY)/{{cookiecutter.project_slug}}:$(GIT_HASH)
	kustomize build k8s/prod | \
		sed -e "s;{% raw %}{{DOCKER_REPO}}{% endraw %};$(DOCKER_REGISTRY)/{{cookiecutter.project_slug}};g" \
		    -e "s;{% raw %}{{GIT_COMMIT_SHA}}{% endraw %};$(GIT_HASH);g" | \
		kubectl apply -f -
