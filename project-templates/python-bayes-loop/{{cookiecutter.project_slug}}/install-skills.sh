#!/bin/bash
# Per-skill installs, selected to match the capabilities in README.md:
# PyMC modeling of a new dataset (priors, a regression-style model, diagnostics,
# PyTensor shape errors),
# a Datastar (SSE) dashboard, deployed to Kubernetes.
# Each add fetches the skill's latest version; commit the resulting
# skills-lock.json. `npx skills experimental_install` restores that exact set.
#
# The project's own skill, .claude/skills/new-model, is committed here, not
# installed: it describes this codebase's model contract.
set -e

# PyMC Labs' skills, as published on Decision Hub (hub.decision.ai/orgs/pymc-labs),
# installed from the repo the hub syncs from. `dhub install` would put them in
# ~/.claude/skills for every project; this keeps them here, pinned in the lockfile.
npx skills add pymc-labs/python-analytics-skills -s pymc-modeling -y
npx skills add pymc-labs/python-analytics-skills -s prior-elicitation -y
npx skills add pymc-labs/python-analytics-skills -s arviz-diagnostics -y
npx skills add pymc-labs/python-analytics-skills -s pytensor-workflows -y
npx skills add brojonat/llmsrules -s bayesian-regression -y
npx skills add brojonat/llmsrules -s datastar -y
npx skills add brojonat/llmsrules -s k8s-deployment -y
