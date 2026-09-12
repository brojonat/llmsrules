BIN     := {{cookiecutter.project_slug}}
PKG     := ./cmd/$(BIN)
VERSION := $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
LDFLAGS := -ldflags "-X main.version=$(VERSION)"
PORT    ?= {{cookiecutter.default_port}}

.DEFAULT_GOAL := help

.PHONY: help
help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Resolve dependencies and install dev tools
	go mod tidy
	go install github.com/air-verse/air@latest

.PHONY: build
build: ## Build ./$(BIN)
	go build $(LDFLAGS) -o $(BIN) $(PKG)

.PHONY: install
install: ## go install into $(GOPATH)/bin
	go install $(LDFLAGS) $(PKG)

.PHONY: test
test: ## Run tests (temp-dir fixtures only)
	go test ./...

.PHONY: lint
lint: ## gofmt + go vet
	@test -z "$$(gofmt -l .)" || (gofmt -l . && exit 1)
	go vet ./...

.PHONY: run-serve
run-serve: ## Run the app with hot reload (Air), tee to logs/serve.log
	@mkdir -p logs
	air 2>&1 | tee logs/serve.log

.PHONY: run
run: build ## Run the built binary without hot reload, tee to logs/serve.log
	@mkdir -p logs
	./$(BIN) serve --addr 127.0.0.1:$(PORT) 2>&1 | tee logs/serve.log

.PHONY: stop
stop: ## Kill whatever is listening on $(PORT) (an orphaned Air child, usually)
	@-kill $$(lsof -nP -t -iTCP:$(PORT) -sTCP:LISTEN) 2>/dev/null || true

.PHONY: clean
clean: ## Remove build output, logs, tmp
	rm -rf $(BIN) logs tmp
