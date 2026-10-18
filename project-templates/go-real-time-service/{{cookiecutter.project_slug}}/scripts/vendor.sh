#!/bin/sh
# Fetch the vendored client libraries that are missing. They are ordinary
# committed files, so this only touches the network on a fresh checkout;
# `mise run update-assets` deletes them first to pull new versions.
set -eu

static=web/resources/static
styles=web/resources/styles

fetch() {
	[ -f "$1" ] && return 0
	mkdir -p "$(dirname "$1")"
	curl -sSfL -o "$1" "$2"
}

fetch "$static/datastar/datastar.js" https://raw.githubusercontent.com/starfederation/datastar/develop/bundles/datastar.js
fetch "$styles/daisyui/daisyui.js" https://github.com/saadeghi/daisyui/releases/latest/download/daisyui.js
fetch "$styles/daisyui/daisyui-theme.js" https://github.com/saadeghi/daisyui/releases/latest/download/daisyui-theme.js
