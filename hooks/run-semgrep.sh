#!/usr/bin/env bash
#
# Skip gracefully when semgrep is missing or unauthenticated so contributors
# without a Semgrep account don't get blocked.
set -euo pipefail

if ! command -v semgrep >/dev/null 2>&1; then
    echo "Warning: semgrep not found on PATH. Install it (e.g. via mise: 'mise use semgrep@latest' && 'mise install'). Skipping semgrep." >&2
    exit 0
fi

if ! semgrep show identity >/dev/null 2>&1; then
    echo "Warning: not logged in to semgrep.dev. Run 'semgrep login' first. Skipping semgrep." >&2
    exit 0
fi

exec semgrep "$@"
