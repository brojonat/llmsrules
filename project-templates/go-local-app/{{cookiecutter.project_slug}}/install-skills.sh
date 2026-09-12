#!/bin/bash
# Per-skill installs, selected to match the capabilities in README.md.
# Commit the resulting skills-lock.json.
set -e

npx skills add brojonat/llmsrules -s urfave-cli -y
npx skills add brojonat/llmsrules -s datastar -y
