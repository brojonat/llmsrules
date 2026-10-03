#!/bin/sh
# Render k8s/prod with the image for HEAD. One copy of the substitution for
# preview, deploy and delete. (A script, not inline in mise.toml: mise renders
# task scripts as templates and would eat the placeholders.)
set -e
{% raw %}kustomize build --load-restrictor=LoadRestrictionsNone k8s/prod \
  | sed -e "s;{{DOCKER_REPO}};${DOCKER_REPO:-{% endraw %}{{cookiecutter.docker_repo}}{% raw %}};g" \
        -e "s;{{IMG_TAG}};$(git rev-parse --short HEAD);g"{% endraw %}
