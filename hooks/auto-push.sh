#!/usr/bin/env bash
#
# post-commit hook: push the commit just made to the current branch's upstream.
#
# Usage: auto-push.sh [--branch=<glob>]... [--set-upstream]
#
#   --branch=<glob>  Only push branches matching the glob. Repeatable. With no
#                    --branch, every branch that has an upstream is pushed.
#   --set-upstream   Push a branch with no upstream to remote.pushDefault (or
#                    origin) and set the upstream. Without it, such branches are
#                    skipped, so local scratch branches stay local.
#
# Never force-pushes. Every skip exits 0 with a note; a push that was attempted
# or blocked by divergence exits 1, so prek reports it. The commit itself is
# already made either way: post-commit can't undo it.
set -euo pipefail

note() { echo "auto-push: $*" >&2; }

branch_globs=()
set_upstream=0
for arg in "$@"; do
	case "$arg" in
	--branch=*) branch_globs+=("${arg#--branch=}") ;;
	--set-upstream) set_upstream=1 ;;
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

IFS='|' read -r upstream upstream_remote push_ref push_remote < <(
	git for-each-ref --format='%(upstream)|%(upstream:remotename)|%(push)|%(push:remotename)' "refs/heads/${branch}"
)

if [ -z "$upstream" ]; then
	if [ "$set_upstream" -eq 0 ]; then
		note "skipping: ${branch} has no upstream (pass --set-upstream to publish it)"
		exit 0
	fi
	remote=$(git config --get remote.pushDefault || echo origin)
	if ! git remote get-url "$remote" >/dev/null 2>&1; then
		note "skipping: remote '${remote}' doesn't exist"
		exit 0
	fi
	note "publishing ${branch} to ${remote}"
	exec git push --set-upstream "$remote" "HEAD:refs/heads/${branch}"
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

exec git push "$remote" "HEAD:refs/heads/${dest}"
