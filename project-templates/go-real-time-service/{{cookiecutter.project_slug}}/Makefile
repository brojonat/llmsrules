SHELL := /bin/bash

STATIC_DIR := web/resources/static
STYLES_DIR := web/resources/styles

# Vendored client libraries. These are real files with real rules, so Make
# fetches them only when they are missing.
DATASTAR_JS   := $(STATIC_DIR)/datastar/datastar.js
DAISYUI_JS    := $(STYLES_DIR)/daisyui/daisyui.js
DAISYUI_THEME := $(STYLES_DIR)/daisyui/daisyui-theme.js
VENDORED      := $(DATASTAR_JS) $(DAISYUI_JS) $(DAISYUI_THEME)

define setup_env
	$(eval ENV_FILE := $(1))
	$(eval include $(1))
	$(eval export)
endef

.PHONY: help
help: ## Show available targets
	@awk -F ':.*?## ' '/^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: setup
setup: ## Install dependencies and run codegen
	go mod tidy
	$(MAKE) generate css

# ---------------------------------------------------------------------------
# Codegen. Both outputs are gitignored, so every target that compiles or runs
# the app depends on them.
# ---------------------------------------------------------------------------

.PHONY: generate
generate: ## Generate Go code from .templ files
	go tool templ generate

.PHONY: css
css: $(VENDORED) ## Compile the Tailwind/DaisyUI stylesheet
	go tool gotailwind -i $(STYLES_DIR)/styles.css -o $(STATIC_DIR)/index.css

$(DATASTAR_JS):
	@mkdir -p $(@D)
	curl -sSfL -o $@ https://raw.githubusercontent.com/starfederation/datastar/develop/bundles/datastar.js

$(DAISYUI_JS):
	@mkdir -p $(@D)
	curl -sSfL -o $@ https://github.com/saadeghi/daisyui/releases/latest/download/daisyui.js

$(DAISYUI_THEME):
	@mkdir -p $(@D)
	curl -sSfL -o $@ https://github.com/saadeghi/daisyui/releases/latest/download/daisyui-theme.js

.PHONY: update-assets
update-assets: ## Re-download the vendored client libraries
	rm -f $(VENDORED)
	$(MAKE) $(VENDORED)

# ---------------------------------------------------------------------------
# Build and test
# ---------------------------------------------------------------------------

.PHONY: build
build: generate css ## Build the production binary
	go build -tags=prod -o bin/{{cookiecutter.project_slug}} ./cmd/server

.PHONY: test
test: generate ## Run tests
	go test ./... -race

.PHONY: lint
lint: generate ## Run linter
	golangci-lint run

.PHONY: clean
clean: ## Remove build artifacts and generated code
	rm -rf bin/ tmp/ logs/*.log $(STATIC_DIR)/index.css
	find . -name '*_templ.go' -delete

# ---------------------------------------------------------------------------
# Development. air's build command re-runs templ generate, so editing a .templ
# file is enough and tmp/main is never stale.
# ---------------------------------------------------------------------------

.PHONY: run-dev
run-dev: css ## Run the server with hot reload (logs to logs/server.log)
	@mkdir -p logs
	$(call setup_env, .env.server)
	go tool air -c .air.toml 2>&1 | tee logs/server.log

.PHONY: run-css-dev
run-css-dev: $(VENDORED) ## Watch and rebuild the stylesheet (logs to logs/css.log)
	@mkdir -p logs
	go tool gotailwind -i $(STYLES_DIR)/styles.css -o $(STATIC_DIR)/index.css -w 2>&1 | tee logs/css.log

.PHONY: start-dev
start-dev: ## Start tmux dev session (server + stylesheet watcher)
	@tmux new-session -d -s {{cookiecutter.project_slug}} -n server
	@tmux send-keys -t {{cookiecutter.project_slug}}:server 'make run-dev' C-m
	@tmux new-window -t {{cookiecutter.project_slug}} -n css
	@tmux send-keys -t {{cookiecutter.project_slug}}:css 'make run-css-dev' C-m
	@echo "Dev session '{{cookiecutter.project_slug}}' started."
	@echo "  server -> http://localhost:8080  (logs/server.log)"
	@echo "  css    -> stylesheet watcher     (logs/css.log)"
	@echo "Attach with: tmux attach -t {{cookiecutter.project_slug}}"

.PHONY: stop-dev
stop-dev: ## Stop the tmux dev session
	@tmux kill-session -t {{cookiecutter.project_slug}} || true

.PHONY: run
run: build ## Run the production binary
	$(call setup_env, .env.server)
	./bin/{{cookiecutter.project_slug}} server

# ---------------------------------------------------------------------------
# Deployment
# ---------------------------------------------------------------------------

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

.PHONY: logs
logs: ## Tail production logs
	kubectl logs -f deployment/{{cookiecutter.project_slug}}
