#!/bin/sh
# Bring the warehouse up to date: the one thing any scheduler calls. Both
# steps skip themselves when there's nothing to do (content hashes, recipe
# hash), so running this often is cheap. A running server notices the new
# manifest and hot-swaps the warehouse; nothing needs restarting.
#
# Exits non-zero without touching the live warehouse if the new data shrank
# (a broken source): the job fails and the site keeps serving the last good
# build.
set -eu
{{cookiecutter.project_slug}} generate
{{cookiecutter.project_slug}} build
