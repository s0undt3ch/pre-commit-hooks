#!/usr/bin/env bash
#
# post-commit hook: push the commit just made to the current branch's upstream.
#
# Usage: auto-push.sh [--branch=<glob>]... [--set-upstream] [--timeout=<seconds>]
#
#   --branch=<glob>  Only push branches matching the glob. Repeatable. With no
#                    --branch, every branch that has an upstream is pushed.
#   --set-upstream   Push a branch with no upstream to remote.pushDefault (or
#                    origin) and set the upstream. Without it, such branches are
#                    skipped, so local scratch branches stay local.
#   --timeout=<sec>  Abort the push after this long (default 60, 0 = never).
#                    Needs `timeout` (GNU coreutils; `gtimeout` on macOS);
#                    without it the push is unbounded.
#
# Never force-pushes. Every skip exits 0 with a note; a failed or refused push
# exits non-zero (124 on timeout) so prek reports it; bad arguments exit 2. The
# commit itself is already made either way: post-commit can't undo it.
set -euo pipefail

note() { echo "auto-push: $*" >&2; }

branch_globs=()
set_upstream=0
timeout_secs=60
for arg in "$@"; do
	case "$arg" in
	--branch=*) branch_globs+=("${arg#--branch=}") ;;
	--set-upstream) set_upstream=1 ;;
	--timeout=*)
		timeout_secs="${arg#--timeout=}"
		if ! [[ "$timeout_secs" =~ ^[0-9]+$ ]]; then
			note "--timeout needs whole seconds, got: ${timeout_secs}"
			exit 2
		fi
		;;
	*)
		note "unknown argument: $arg"
		exit 2
		;;
	esac
done

# git fires post-commit for every commit a rebase or a multi-commit
# cherry-pick/revert replays; pushing mid-way would publish half a rewrite.
for state in rebase-merge rebase-apply sequencer; do
	if [ -e "$(git rev-parse --git-path "$state")" ]; then
		note "skipping: ${state} in progress"
		exit 0
	fi
done

if ! branch=$(git symbolic-ref --quiet --short HEAD); then
	note "skipping: detached HEAD"
	exit 0
fi

if [ "${#branch_globs[@]}" -gt 0 ]; then
	matched=0
	for glob in "${branch_globs[@]}"; do
		# shellcheck disable=SC2053 # glob match is the point
		if [[ "$branch" == $glob ]]; then
			matched=1
			break
		fi
	done
	if [ "$matched" -eq 0 ]; then
		note "skipping: ${branch} doesn't match --branch"
		exit 0
	fi
fi

export GIT_TERMINAL_PROMPT=0

# One call per field: refnames may contain any printable delimiter.
ref_field() { git for-each-ref --format="%(${1})" "refs/heads/${branch}"; }
upstream=$(ref_field upstream)
upstream_remote=$(ref_field upstream:remotename)
push_ref=$(ref_field push)
push_remote=$(ref_field push:remotename)

# A hung remote would otherwise block every commit, scripted ones included.
push() {
	local timeout_cmd rc=0
	timeout_cmd=$(command -v timeout || command -v gtimeout || true)
	if [ "$timeout_secs" -gt 0 ] && [ -n "$timeout_cmd" ]; then
		"$timeout_cmd" "$timeout_secs" git push "$@" || rc=$?
	else
		git push "$@" || rc=$?
	fi
	# 124 is GNU timeout's "command timed out" status.
	if [ "$rc" -eq 124 ]; then
		note "push timed out after ${timeout_secs}s; the commit is still local"
	fi
	return "$rc"
}

if [ -z "$upstream" ]; then
	if [ "$set_upstream" -eq 0 ]; then
		note "skipping: ${branch} has no upstream (pass --set-upstream to publish it)"
		exit 0
	fi
	remote=$(git config --get remote.pushDefault || echo origin)
	note "publishing ${branch} to ${remote}"
	push --set-upstream "$remote" "HEAD:refs/heads/${branch}"
	exit
fi

# Empty when push.default can't map this branch (e.g. simple + differently named
# upstream), the case where a bare `git push` would refuse too.
if [ -z "$push_ref" ]; then
	note "skipping: git has no push destination for ${branch} (check push.default)"
	exit 0
fi

remote=${push_remote:-$upstream_remote}
dest=${push_ref#refs/remotes/"${remote}"/}

# push.default=current names a push ref even for a branch never pushed, so
# require the tracking ref to exist before treating the branch as published.
if ! git rev-parse --quiet --verify "${push_ref}^{commit}" >/dev/null; then
	note "skipping: ${push_ref} doesn't exist yet (push ${branch} once by hand)"
	exit 0
fi

if ! git merge-base --is-ancestor "$push_ref" HEAD; then
	note "not pushing: ${branch} has diverged from ${push_ref} (amended or rebased?). Never force-pushes; sort it out by hand."
	exit 1
fi

# Still a fast-forward (checked above). The lease only makes the push fail if
# the remote branch is no longer where the tracking ref says, e.g. deleted
# after a merge, instead of quietly recreating it.
push --force-with-lease="refs/heads/${dest}:$(git rev-parse "$push_ref")" \
	"$remote" "HEAD:refs/heads/${dest}"
