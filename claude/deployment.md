# Frontend

The frontend is typically a JavaScript or Flutter app that gets deployed via Vercel. This has all sorts of benefits that make it preferable to serving it from our own Kubernetes infrastructure, so we might as well make use of that.

# Backend

Here's an example layout for a Golang based webserver (this is only a subset of the directories). The main thing to pay attention to here is the location of the Makefile, Dockerfile, and the layout of the k8s directories for deployment scripts.

```plaintext
.
|____cmd
|____bin
|____Dockerfile
|____Makefile
|____server
| |____k8s
| | |____prod
| | | |____server.yaml
| | | |____ingress.yaml
| | | |____kustomization.yaml
|____worker
| |____k8s
| | |____prod
| | | |____kustomization.yaml
| | | |____worker.yaml
```

Example Makefile for deploying these services:

```Makefile
#!/usr/bin/env bash

# Set the shell for make explicitly
SHELL := /bin/bash

define setup_env
        $(eval ENV_FILE := $(1))
        $(eval include $(1))
        $(eval export)
endef

help:
	@echo "Available targets:"
	@awk -F ':.*?## ' '/^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST) | sort

build-push-cli: ## Build and push CLI Docker image with git hash tag (used by deploy targets)
	$(call setup_env, .env.server.prod)
	$(eval GIT_HASH := $(shell git rev-parse --short HEAD))
	$(eval DYNAMIC_TAG := brojonat/abb-cli:$(GIT_HASH))
	@echo "Building and pushing image: $(DYNAMIC_TAG)"
	docker build -f Dockerfile -t $(DYNAMIC_TAG) .
	docker push $(DYNAMIC_TAG)

# Deploy server component
deploy-server: ## Deploy server to Kubernetes (prod)
	$(call setup_env, .env.server.prod)
	@$(MAKE) build-push-cli
	$(eval GIT_HASH := $(shell git rev-parse --short HEAD))
	$(eval DYNAMIC_TAG := brojonat/abb-cli:$(GIT_HASH))
	@echo "Applying server deployment with image: $(DYNAMIC_TAG)"
	kustomize build --load-restrictor=LoadRestrictionsNone server/k8s/prod | \
	sed -e "s;{{DOCKER_REPO}};brojonat/abb-cli;g" \
		-e "s;{{GIT_COMMIT_SHA}};$(GIT_HASH);g" | \
		kubectl apply -f -
	# No need to patch anymore, the image tag change forces the rollout
	@echo "Server deployment applied."

# Deploy worker component
deploy-worker: ## Deploy worker to Kubernetes (prod)
	$(call setup_env, .env.worker.prod)
	@$(MAKE) build-push-cli
	$(eval GIT_HASH := $(shell git rev-parse --short HEAD))
	$(eval DYNAMIC_TAG := brojonat/abb-cli:$(GIT_HASH))
	@echo "Applying worker deployment with image: $(DYNAMIC_TAG)"
	kustomize build --load-restrictor=LoadRestrictionsNone worker/k8s/prod | \
	sed -e "s;{{DOCKER_REPO}};brojonat/abb-cli;g" \
		-e "s;{{GIT_COMMIT_SHA}};$(GIT_HASH);g" | \
		kubectl apply -f -
	# No need to patch anymore, the image tag change forces the rollout
	@echo "Worker deployment applied."
```

Example Dockerfile for a Go based HTTP server:

```Dockerfile
# ---- Builder Stage ----
FROM golang:1.24-alpine AS builder

# Install build dependencies AND CA certificates
RUN apk update && apk add --no-cache git build-base ca-certificates
RUN update-ca-certificates

# Set working directory
WORKDIR /app

# Copy go mod and sum files FIRST
COPY go.mod go.sum ./
# Download dependencies - this layer is cached if go.mod/go.sum don't change
RUN go mod download

# Copy ONLY the necessary source directories
COPY cmd/ ./cmd/
COPY server/ ./server/
COPY worker/ ./worker/

# Build the application binary statically for Linux
# Use ldflags to strip debug info and reduce binary size
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /bin/abb cmd/abb/*.go

# ---- Final Stage ----
FROM alpine:latest

COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

WORKDIR /app

# Copy the built binary from the builder stage
COPY --from=builder /bin/abb /abb

# Expose the port the server listens on
EXPOSE 8080

# Set the default entrypoint command to run the server
# Kubernetes worker deployment should override this with command/args
CMD ["/abb", "run", "http-server"]%
```

A Python backend would follow a similar pattern, but adhere to idiomatic Python project layouts. The main IMPORTANT pattern is to build and image and redploy services with `kustomize` overlays.
