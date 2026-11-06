#!/bin/sh
# Build and push the image for HEAD, then apply k8s/prod with the image filled
# in. A script rather than a mise task because the manifest placeholders look
# like Tera templates, which mise would try to render.
set -eu

test -f .env.prod || { echo ".env.prod is missing; copy .env.example" >&2; exit 1; }
. ./.env.prod

repo="$DOCKER_REGISTRY/{{cookiecutter.project_slug}}"
sha=$(git rev-parse --short HEAD)

docker build -t "$repo:$sha" .
docker push "$repo:$sha"
kustomize build k8s/prod |
	sed -e "s;{% raw %}{{DOCKER_REPO}}{% endraw %};$repo;g" -e "s;{% raw %}{{GIT_COMMIT_SHA}}{% endraw %};$sha;g" |
	kubectl apply -f -
