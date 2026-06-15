"""Tests for hooks/run-tool.sh — the generic system-tool forwarder.

Each test drives the real script through subprocess. A fake tool is dropped
into a temp bin dir placed first on PATH; it records its argv (one arg per
line) and exits with a chosen code. Missing-tool cases use a name that cannot
exist on any PATH, so the real system PATH is irrelevant.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RUN_TOOL = _REPO_ROOT / "hooks" / "run-tool.sh"

# A tool name guaranteed not to exist on PATH.
MISSING = "no-such-tool-xyzzy-42"


@pytest.fixture
def bindir(tmp_path: Path) -> Path:
    d = tmp_path / "bin"
    d.mkdir()
    return d


def make_tool(bindir: Path, name: str = "faketool", *, exit_code: int = 0) -> Path:
    """Create an executable fake tool that logs its argv and exits `exit_code`.

    Returns the path to the argv log file (one argument per line)."""
    log = bindir / f"{name}.argv"
    script = f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{log}"\nexit {exit_code}\n'
    p = bindir / name
    p.write_text(script)
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return log


def run(args: list[str], bindir: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        [str(_RUN_TOOL), *args], env=env, capture_output=True, text=True
    )


def logged_argv(log: Path) -> list[str]:
    return log.read_text().splitlines()


def test_present_tool_exits_zero_and_forwards_args(bindir: Path) -> None:
    log = make_tool(bindir, exit_code=0)
    result = run(["faketool", "a", "b", "c"], bindir)
    assert result.returncode == 0
    assert logged_argv(log) == ["a", "b", "c"]


def test_present_tool_propagates_nonzero_exit(bindir: Path) -> None:
    make_tool(bindir, exit_code=3)
    result = run(["faketool", "x"], bindir)
    assert result.returncode == 3


def test_exit_zero_does_not_mask_a_running_tools_failure(bindir: Path) -> None:
    log = make_tool(bindir, exit_code=4)
    result = run(["faketool", "--exit-zero", "x"], bindir)
    assert (
        result.returncode == 4
    )  # tool ran and failed; --exit-zero only guards a MISSING tool
    assert logged_argv(log) == ["x"]  # --exit-zero stripped


def test_exit_zero_is_stripped_from_anywhere(bindir: Path) -> None:
    log = make_tool(bindir, exit_code=0)
    result = run(["faketool", "a", "--exit-zero", "b"], bindir)
    assert result.returncode == 0
    assert logged_argv(log) == ["a", "b"]


def test_missing_tool_hard_errors(bindir: Path) -> None:
    result = run([MISSING, "a"], bindir)
    assert result.returncode == 1
    assert MISSING in result.stderr
    assert "not found on PATH" in result.stderr


def test_missing_tool_with_exit_zero_warns_and_succeeds(bindir: Path) -> None:
    result = run([MISSING, "--exit-zero", "a"], bindir)
    assert result.returncode == 0
    assert "Skipping" in result.stderr


def test_only_tool_name_no_args_is_a_noop(bindir: Path) -> None:
    log = make_tool(bindir, exit_code=0)
    result = run(["faketool"], bindir)
    assert result.returncode == 0
    assert not log.exists()  # tool was never invoked


def test_no_tool_name_is_a_usage_error(bindir: Path) -> None:
    result = run([], bindir)
    assert result.returncode == 2
    assert "tool name" in result.stderr


def test_default_args_then_files_preserve_order(bindir: Path) -> None:
    log = make_tool(bindir, exit_code=0)
    result = run(["faketool", "git", "--staged", "f1", "f2"], bindir)
    assert result.returncode == 0
    assert logged_argv(log) == ["git", "--staged", "f1", "f2"]


def test_missing_tool_with_no_args_still_hard_errors(bindir: Path) -> None:
    # The PATH check fires before the empty-args no-op, so a missing tool is a
    # hard error even when there is nothing to forward.
    result = run([MISSING], bindir)
    assert result.returncode == 1
    assert "not found on PATH" in result.stderr


def test_exit_zero_must_follow_the_tool_name(bindir: Path) -> None:
    # --exit-zero is only meaningful after the tool name. Placed first it IS
    # taken as the tool name, so it resolves as a missing tool (hard error),
    # not as the soften-missing-tool flag.
    log = make_tool(bindir, exit_code=0)  # a real faketool exists, but is not arg 1
    result = run(["--exit-zero", "faketool", "x"], bindir)
    assert result.returncode == 1
    assert "not found on PATH" in result.stderr
    assert not log.exists()  # faketool was never invoked
