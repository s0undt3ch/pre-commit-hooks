"""Drive hooks/auto-push.sh against a throwaway clone of a bare remote."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_AUTO_PUSH = Path(__file__).resolve().parents[1] / "hooks" / "auto-push.sh"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


@pytest.fixture
def git_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the user's global hooksPath, signing and push.default out of the tests.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "test@example.com")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def auto_push(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_AUTO_PUSH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=os.environ,
    )


def commit(cwd: Path, name: str) -> str:
    (cwd / name).write_text(name)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", name)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def remote(tmp_path: Path, git_env: None) -> Path:
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    return bare


@pytest.fixture
def clone(tmp_path: Path, remote: Path) -> Path:
    work = tmp_path / "work"
    git(tmp_path, "init", "-q", "-b", "main", str(work))
    git(work, "remote", "add", "origin", str(remote))
    commit(work, "first")
    git(work, "push", "-q", "-u", "origin", "main")
    return work


def remote_head(remote: Path, branch: str = "main") -> str:
    return git(remote, "rev-parse", branch)


def test_pushes_new_commit_to_upstream(clone: Path, remote: Path) -> None:
    sha = commit(clone, "second")
    result = auto_push(clone)
    assert result.returncode == 0, result.stderr
    assert remote_head(remote) == sha


def test_skips_during_rebase(clone: Path, remote: Path) -> None:
    before = remote_head(remote)
    commit(clone, "second")
    (clone / git(clone, "rev-parse", "--git-path", "rebase-merge")).mkdir()
    result = auto_push(clone)
    assert result.returncode == 0, result.stderr
    assert "rebase-merge in progress" in result.stderr
    assert remote_head(remote) == before


def test_skips_detached_head(clone: Path, remote: Path) -> None:
    before = remote_head(remote)
    git(clone, "switch", "-q", "--detach")
    commit(clone, "second")
    result = auto_push(clone)
    assert result.returncode == 0, result.stderr
    assert "detached HEAD" in result.stderr
    assert remote_head(remote) == before


def test_skips_branch_not_matching_glob(clone: Path, remote: Path) -> None:
    git(clone, "switch", "-q", "-c", "feature/x")
    git(clone, "push", "-q", "-u", "origin", "feature/x")
    before = remote_head(remote, "feature/x")
    commit(clone, "second")
    result = auto_push(clone, "--branch=main", "--branch=release/*")
    assert result.returncode == 0, result.stderr
    assert remote_head(remote, "feature/x") == before


def test_pushes_branch_matching_glob(clone: Path, remote: Path) -> None:
    git(clone, "switch", "-q", "-c", "release/1")
    git(clone, "push", "-q", "-u", "origin", "release/1")
    sha = commit(clone, "second")
    result = auto_push(clone, "--branch=release/*")
    assert result.returncode == 0, result.stderr
    assert remote_head(remote, "release/1") == sha


def test_skips_branch_without_upstream(clone: Path, remote: Path) -> None:
    git(clone, "switch", "-q", "-c", "scratch")
    commit(clone, "second")
    result = auto_push(clone)
    assert result.returncode == 0, result.stderr
    assert "no upstream" in result.stderr
    assert git(remote, "branch", "--list", "scratch") == ""


def test_skips_never_pushed_branch_under_push_default_current(
    clone: Path, remote: Path
) -> None:
    git(clone, "config", "push.default", "current")
    git(clone, "switch", "-q", "-c", "scratch", "--track", "origin/main")
    commit(clone, "second")
    result = auto_push(clone)
    assert result.returncode == 0, result.stderr
    assert "doesn't exist yet" in result.stderr
    assert git(remote, "branch", "--list", "scratch") == ""


def test_set_upstream_publishes_new_branch(clone: Path, remote: Path) -> None:
    git(clone, "switch", "-q", "-c", "scratch")
    sha = commit(clone, "second")
    result = auto_push(clone, "--set-upstream")
    assert result.returncode == 0, result.stderr
    assert remote_head(remote, "scratch") == sha
    assert git(clone, "rev-parse", "--abbrev-ref", "@{u}") == "origin/scratch"


def test_pushes_to_differently_named_upstream(clone: Path, remote: Path) -> None:
    git(clone, "config", "push.default", "upstream")
    git(clone, "switch", "-q", "-c", "local-name", "--track", "origin/main")
    sha = commit(clone, "second")
    result = auto_push(clone)
    assert result.returncode == 0, result.stderr
    assert remote_head(remote) == sha
    assert git(remote, "branch", "--list", "local-name") == ""


def test_refuses_to_push_after_amending_pushed_commit(
    clone: Path, remote: Path
) -> None:
    before = remote_head(remote)
    git(clone, "commit", "-q", "--amend", "-m", "amended")
    result = auto_push(clone)
    assert result.returncode == 1
    assert "diverged" in result.stderr
    assert remote_head(remote) == before


def test_rejects_unknown_argument(clone: Path) -> None:
    result = auto_push(clone, "--force")
    assert result.returncode == 2
    assert "unknown argument" in result.stderr


def test_real_rebase_does_not_push(clone: Path, remote: Path) -> None:
    hook = clone / git(clone, "rev-parse", "--git-path", "hooks") / "post-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(f'#!/bin/sh\nexec "{_AUTO_PUSH}"\n')
    hook.chmod(0o755)
    commit(clone, "second")
    commit(clone, "third")
    pushed = remote_head(remote)
    git(clone, "rebase", "-q", "--force-rebase", "HEAD~2")
    assert remote_head(remote) == pushed
    assert git(clone, "rev-parse", "HEAD") != pushed
