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
run-dev: ## Run server with hot reload (logs to logs/)
	@mkdir -p logs
	$(call setup_env, .env.server)
	air -c .air.toml 2>&1 | tee logs/server.log

.PHONY: run
run: build ## Run production server
	$(call setup_env, .env.server)
	./bin/{{cookiecutter.project_slug}} server

.PHONY: run-worker-dev
run-worker-dev: ## Run worker with hot reload (logs to logs/)
	@mkdir -p logs
	$(call setup_env, .env.worker)
	air -c .air.worker.toml 2>&1 | tee logs/worker.log

.PHONY: run-worker
run-worker: build ## Run production worker
	$(call setup_env, .env.worker)
	./bin/{{cookiecutter.project_slug}} worker

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

.PHONY: deploy-server
deploy-server: ## Deploy server to Kubernetes
	$(call setup_env, .env.prod)
	$(eval GIT_HASH := $(shell git rev-parse --short HEAD))
	docker build -t $(DOCKER_REGISTRY)/{{cookiecutter.project_slug}}:$(GIT_HASH) .
	docker push $(DOCKER_REGISTRY)/{{cookiecutter.project_slug}}:$(GIT_HASH)
	kustomize build k8s/prod | \
		sed -e "s;{% raw %}{{DOCKER_REPO}}{% endraw %};$(DOCKER_REGISTRY)/{{cookiecutter.project_slug}};g" \
		    -e "s;{% raw %}{{GIT_COMMIT_SHA}}{% endraw %};$(GIT_HASH);g" | \
		kubectl apply -f -

.PHONY: deploy-worker
deploy-worker: ## Deploy worker to Kubernetes
	$(call setup_env, .env.prod)
	$(eval GIT_HASH := $(shell git rev-parse --short HEAD))
	docker build -t $(DOCKER_REGISTRY)/{{cookiecutter.project_slug}}:$(GIT_HASH) .
	docker push $(DOCKER_REGISTRY)/{{cookiecutter.project_slug}}:$(GIT_HASH)
	kustomize build worker/k8s/prod | \
		sed -e "s;{% raw %}{{DOCKER_REPO}}{% endraw %};$(DOCKER_REGISTRY)/{{cookiecutter.project_slug}};g" \
		    -e "s;{% raw %}{{GIT_COMMIT_SHA}}{% endraw %};$(GIT_HASH);g" | \
		kubectl apply -f -

.PHONY: deploy
deploy: deploy-server deploy-worker ## Deploy server and worker to Kubernetes

.PHONY: logs-server
logs-server: ## Tail server logs
	kubectl logs -f deployment/{{cookiecutter.project_slug}}

.PHONY: logs-worker
logs-worker: ## Tail worker logs
	kubectl logs -f deployment/{{cookiecutter.project_slug}}-worker
