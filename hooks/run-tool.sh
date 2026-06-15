#!/usr/bin/env bash
#
# Generic pre-commit forwarder: run a system-installed tool from PATH.
#
# Usage: run-tool.sh <tool> [args...]
#
# The first argument is the tool name. Any literal `--exit-zero` token among the
# remaining arguments is consumed (never forwarded) and switches the
# missing-tool behaviour from a hard error to a warning + exit 0. Everything
# else is forwarded to the tool verbatim, in order, and the tool's own exit
# status propagates unchanged.
#
# Why this exists: run the mise-pinned binary already on PATH instead of a
# Docker image or a from-source compile, so a tool's version has a single
# source of truth (mise.toml) and never drifts from a hook's own version pin.
# No Docker, ever.
#
# `--exit-zero` only ever affects the *missing-tool* case — it never suppresses
# a real non-zero exit from a tool that did run.
set -euo pipefail

if [ "$#" -eq 0 ]; then
	echo "Error: run-tool.sh requires a tool name as its first argument." >&2
	exit 2
fi

tool="$1"
shift

exit_zero=0
args=()
for arg in "$@"; do
	case "$arg" in
	--exit-zero) exit_zero=1 ;;
	*) args+=("$arg") ;;
	esac
done

if ! command -v "$tool" >/dev/null 2>&1; then
	msg="${tool} not found on PATH. Install it (e.g. via mise: 'mise use ${tool}@latest' && 'mise install')."
	if [ "$exit_zero" -eq 1 ]; then
		echo "Warning: ${msg} Skipping ${tool} (--exit-zero)." >&2
		exit 0
	fi
	echo "Error: ${msg}" >&2
	exit 1
fi

# Nothing to do: a file-based hook that prek filtered down to nothing, or a
# generic `system-tool` invocation with neither args nor files. Succeed quietly
# rather than invoking the tool bare (some tools, e.g. shellcheck, would then
# read stdin and hang).
if [ "${#args[@]}" -eq 0 ]; then
	exit 0
fi

exec "$tool" "${args[@]}"
