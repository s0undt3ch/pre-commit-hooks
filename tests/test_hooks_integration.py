"""End-to-end tests: drive each real tool through hooks/run-tool.sh on a clean
fixture. Skipped when the tool is not on PATH, so a contributor missing a tool
just skips that test; CI installs every tool via mise and runs them all."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RUN_TOOL = _REPO_ROOT / "hooks" / "run-tool.sh"
_FILES = _REPO_ROOT / "tests" / "files"


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_RUN_TOOL), *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(shutil.which("actionlint") is None, reason="actionlint not on PATH")
def test_actionlint_passes_on_clean_workflow() -> None:
    result = run_tool("actionlint", str(_FILES / "clean_workflow.yml"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not on PATH")
def test_shellcheck_passes_on_clean_script() -> None:
    result = run_tool("shellcheck", str(_FILES / "clean.sh"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("shfmt") is None, reason="shfmt not on PATH")
def test_shfmt_diff_passes_on_clean_script() -> None:
    # -d = report a diff (non-zero) when the file is not already formatted
    result = run_tool("shfmt", "-d", str(_FILES / "clean.sh"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("sqlfluff") is None, reason="sqlfluff not on PATH")
def test_sqlfluff_lint_passes_on_clean_sql() -> None:
    result = run_tool(
        "sqlfluff",
        "lint",
        "--processes",
        "0",
        "--disable-progress-bar",
        str(_FILES / "clean.sql"),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_run_tool_exit_zero_skips_when_tool_truly_missing() -> None:
    # Sanity: --exit-zero path against a guaranteed-missing tool still exits 0.
    # No real tool is involved, so this runs unconditionally (no skipif).
    result = run_tool("no-such-tool-xyzzy-42", "--exit-zero", str(_FILES / "clean.sh"))
    assert result.returncode == 0


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not on PATH")
def test_ruff_check_passes_on_clean_py() -> None:
    result = run_tool("ruff", "check", "--force-exclude", str(_FILES / "clean_py.py"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not on PATH")
def test_ruff_format_check_passes_on_clean_py() -> None:
    result = run_tool(
        "ruff", "format", "--check", "--force-exclude", str(_FILES / "clean_py.py")
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("typos") is None, reason="typos not on PATH")
def test_typos_passes_on_clean_fixture() -> None:
    result = run_tool("typos", str(_FILES / "clean_py.py"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("rumdl") is None, reason="rumdl not on PATH")
def test_rumdl_passes_on_clean_md() -> None:
    result = run_tool("rumdl", "check", str(_FILES / "clean.md"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("codespell") is None, reason="codespell not on PATH")
def test_codespell_passes_on_clean_fixture() -> None:
    result = run_tool("codespell", str(_FILES / "clean_py.py"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("mypy") is None, reason="mypy not on PATH")
def test_mypy_passes_on_clean_py() -> None:
    result = run_tool(
        "mypy",
        "--ignore-missing-imports",
        "--scripts-are-modules",
        str(_FILES / "clean_py.py"),
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("yamllint") is None, reason="yamllint not on PATH")
def test_yamllint_passes_on_clean_yaml() -> None:
    result = run_tool("yamllint", str(_FILES / "clean.yaml"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("yamlfmt") is None, reason="yamlfmt not on PATH")
def test_yamlfmt_lint_passes_on_clean_yaml() -> None:
    # -lint = check-only (non-zero if the file is not already formatted)
    result = run_tool("yamlfmt", "-lint", str(_FILES / "clean.yaml"))
    assert result.returncode == 0, result.stdout + result.stderr
