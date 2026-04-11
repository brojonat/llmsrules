#!/bin/bash
# Install all preferred skills at the project level.
# Run from the root of any project directory.
# After running, commit the resulting skills-lock.json so that
# others (or you on another machine) can restore with:
#   npx skills experimental_install
#
# IMPORTANT: Keep this script in sync with the README. When you add a new
# skill to the "Skills in this repo" or "Third-party skills I like" tables,
# add a corresponding `npx skills add` line here.
set -e

npx skills add brojonat/llmsrules -y
npx skills add anthropics/skills -y
npx skills add obra/superpowers -y
npx skills add pymc-labs/agent-skills -y
npx skills add marimo-team/skills -y
npx skills add marimo-team/marimo-pair -y
npx skills add temporalio/skill-temporal-developer -y
npx skills add planetscale/database-skills -y
npx skills add supabase/agent-skills -y
npx skills add vercel-labs/agent-skills -y
