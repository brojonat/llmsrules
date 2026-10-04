#!/bin/bash
# The belt in tmux: one window per service (db, sample, plots, dev), so you or
# an agent can restart one without touching the others. Each window runs its
# mise task, which tees logs/<name>.log as usual. Data goes in with
# `mise run feed`, a command, not a service.
#
#   loop.sh [up] [NAME...]   start these services (default: all); ones already running are left alone,
#                            so `up db dev` first (to watch the agent) and a later `up` adds the rest
#   loop.sh restart NAME [ARG...]  restart one service, with extra arguments if given; a restarted
#                            sample refits the newest batch (every row fed so far) with the current model
#   loop.sh status           one line per service: running, or exited with its code
#   loop.sh down             Ctrl-C every service (db last, so it checkpoints), then end the session
#
# The session is named after this checkout (plus -cpu under MISE_ENV=cpu), so
# separate checkouts don't collide in tmux. They still share ports: set PORT
# and QUACK_URL (e.g. quack:localhost:9611) in .env to run two at once.
set -euo pipefail

root=${MISE_PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
session=$(basename "$root" | tr -c 'a-zA-Z0-9_\n-' '_')${MISE_ENV:+-$MISE_ENV}
services=(db sample plots dev)

command_for() {
	local name=$1
	shift
	case $name in
	db | sample | plots | dev) echo "mise run $name $*" ;;
	*)
		echo "unknown service '$name': want one of ${services[*]}" >&2
		exit 2
		;;
	esac
}

running() { tmux has-session -t "=$session" 2>/dev/null; }

has_window() { tmux list-windows -t "=$session" -F '#{window_name}' 2>/dev/null | grep -qx "$1"; }

up() {
	local wanted=("$@") started=()
	[ ${% raw %}{#{% endraw %}wanted[@]} -gt 0 ] || wanted=("${services[@]}")
	for name in "${wanted[@]}"; do command_for "$name" >/dev/null; done
	mkdir -p "$root/logs"
	# In services order, so db starts first whatever order the names came in.
	for name in "${services[@]}"; do
		[[ " ${wanted[*]} " == *" $name "* ]] || continue
		has_window "$name" && continue
		if running; then
			tmux new-window -d -t "=$session:" -n "$name" -c "$root" -e "MISE_ENV=${MISE_ENV:-}" "$(command_for "$name")"
		else
			tmux new-session -d -s "$session" -n "$name" -c "$root" -e "MISE_ENV=${MISE_ENV:-}" "$(command_for "$name")"
		fi
		# Keep a crashed service's window, and its last output, until it's restarted.
		tmux set-option -w -t "=$session:$name" remain-on-exit on
		started+=("$name")
	done
	if [ ${% raw %}{#{% endraw %}started[@]} -gt 0 ]; then
		echo "started ${started[*]} in $session; attach with: tmux attach -t $session" >&2
	else
		echo "${wanted[*]} already running in $session" >&2
	fi
}

restart() {
	running || { echo "$session isn't running; start it with: mise run loop" >&2; exit 1; }
	tmux respawn-window -k -t "=$session:$1" -c "$root" -e "MISE_ENV=${MISE_ENV:-}" "$(command_for "$@")"
}

status() {
	running || { echo "$session isn't running"; return 0; }
	tmux list-windows -t "=$session" -F '#{window_name} #{?pane_dead,exited #{pane_dead_status},running}'
}

down() {
	running || return 0
	for name in sample plots dev db; do
		has_window "$name" || continue  # tmux resolves a missing window name to another window
		tmux send-keys -t "=$session:$name" C-c 2>/dev/null || true
		# Wait up to 30 s for it to exit: the sampler finishes its current fit, the db checkpoints.
		for _ in $(seq 60); do
			[ "$(tmux display-message -p -t "=$session:$name" '#{pane_dead}' 2>/dev/null || echo 1)" = 1 ] && break
			sleep 0.5
		done
	done
	tmux kill-session -t "=$session"
}

case ${1:-up} in
up) shift || true; up "$@" ;;
restart)
	[ $# -ge 2 ] || { echo "usage: loop.sh restart {${services[*]// /|}} [ARG...]" >&2; exit 2; }
	shift
	command_for "$@" >/dev/null
	restart "$@"
	;;
status) status ;;
down) down ;;
-h | --help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//' ;;
*)
	echo "usage: loop.sh [up [NAME...]|restart NAME|status|down]" >&2
	exit 2
	;;
esac
