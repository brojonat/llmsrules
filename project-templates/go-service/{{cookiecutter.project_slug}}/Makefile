SHELL := /bin/bash

define setup_env
	$(eval ENV_FILE := $(1))
	$(eval include $(1))
	$(eval export)
endef

.PHONY: help
help: ## Show available targets
	@awk -F ':.*?## ' '/^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: build
build: ## Build the binary
	go build -o bin/{{cookiecutter.project_slug}} ./cmd/server

.PHONY: test
test: ## Run tests
	go test ./... -v -race

.PHONY: lint
lint: ## Run linter
	golangci-lint run

.PHONY: run-dev
run-dev: ## Run with hot reload (logs to logs/)
	@mkdir -p logs
	$(call setup_env, .env.server)
	air 2>&1 | tee logs/server.log

.PHONY: run
run: build ## Run production binary
	$(call setup_env, .env.server)
	./bin/{{cookiecutter.project_slug}}

.PHONY: clean
clean: ## Clean build artifacts
	rm -rf bin/ tmp/ logs/*.log

.PHONY: sqlc
sqlc: ## Generate sqlc code
	sqlc generate

.PHONY: migrate
migrate: ## Run database migrations
	$(call setup_env, .env.server)
	migrate -path migrations -database "$$DATABASE_URL" up

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
