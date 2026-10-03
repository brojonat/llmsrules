#!/bin/bash
# Per-skill installs, selected to match the capabilities in README.md:
# a Datastar (SSE) dashboard over a DuckDB/Parquet warehouse with SQLite
# (FTS5, app DB), deployed to Kubernetes with litestream.
# Commit the resulting skills-lock.json.
set -e

npx skills add brojonat/llmsrules -s datastar -y
npx skills add brojonat/llmsrules -s parquet-analysis -y
npx skills add brojonat/llmsrules -s sqlite -y
npx skills add brojonat/llmsrules -s k8s-deployment -y
npx skills add brojonat/llmsrules -s litestream-k8s -y
