#!/bin/bash
# Per-skill installs, selected to match the capabilities in README.md.
# Commit the resulting skills-lock.json.
set -e

npx skills add brojonat/llmsrules -s rust -y
npx skills add brojonat/llmsrules -s k8s-deployment -y
npx skills add obra/superpowers -s systematic-debugging -y
npx skills add obra/superpowers -s test-driven-development -y
