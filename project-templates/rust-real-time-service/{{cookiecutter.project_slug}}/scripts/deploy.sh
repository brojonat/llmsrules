#!/usr/bin/env bash
# Build and push the image tagged with the current commit, then apply
# k8s/prod with the image pinned to that tag. Needs docker, kustomize, kubectl
# and a pushed commit (the tag is the commit it was built from).
set -euo pipefail

repo="${DOCKER_REPO:-{{cookiecutter.docker_registry}}/{{cookiecutter.project_slug}}}"
sha="$(git rev-parse --short HEAD)"
if [ -n "$(git status --porcelain)" ]; then
  echo "deploy: working tree is dirty; commit first so the tag means something" >&2
  exit 1
fi

docker build -t "$repo:$sha" .
docker push "$repo:$sha"
kustomize build k8s/prod \
  | sed -e "s|{% raw %}{{DOCKER_REPO}}{% endraw %}|$repo|g" -e "s|{% raw %}{{GIT_COMMIT_SHA}}{% endraw %}|$sha|g" \
  | kubectl apply -f -
kubectl -n {{cookiecutter.k8s_namespace}} rollout status deployment/{{cookiecutter.project_slug}}
