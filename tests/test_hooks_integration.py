"""End-to-end tests: drive each real tool through hooks/run-tool.sh on a clean
fixture. Skipped when the tool is not on PATH, so a contributor missing a tool
just skips that test; CI installs every tool via mise and runs them all."""

from __future__ import annotations

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
        check=False,
    )


@pytest.mark.skip_if_binaries_missing("actionlint")
def test_actionlint_passes_on_clean_workflow() -> None:
    result = run_tool("actionlint", str(_FILES / "clean_workflow.yml"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("jactionlint")
def test_jactionlint_passes_on_clean_workflow() -> None:
    result = run_tool("jactionlint", str(_FILES / "clean_workflow.yml"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("jactionlint")
def test_jactionlint_fix_applies_safe_fix(tmp_path: Path) -> None:
    # Zero-width space: this fix, unlike action rules, doesn't track action versions.
    clean = (_FILES / "clean_workflow.yml").read_text()
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(clean.replace('echo "hello"', 'echo "hello\u200b"'))
    result = run_tool("jactionlint", "--fix", str(workflow))
    assert result.returncode == 0, result.stdout + result.stderr
    assert workflow.read_text() == clean


@pytest.mark.skip_if_binaries_missing("shellcheck")
def test_shellcheck_passes_on_clean_script() -> None:
    result = run_tool("shellcheck", str(_FILES / "clean.sh"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("shfmt")
def test_shfmt_diff_passes_on_clean_script() -> None:
    # -d = report a diff (non-zero) when the file is not already formatted
    result = run_tool("shfmt", "-d", str(_FILES / "clean.sh"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("sqlfluff")
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


@pytest.mark.skip_if_binaries_missing("sqruff")
def test_sqruff_lint_passes_on_clean_sql() -> None:
    result = run_tool("sqruff", "lint", str(_FILES / "clean.sql"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("sqruff")
def test_sqruff_lint_fails_without_changing_dirty_sql(tmp_path: Path) -> None:
    sql = tmp_path / "query.sql"
    sql.write_text("select 1  as the_answer\n")
    result = run_tool("sqruff", "lint", str(sql))
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "LT01" in output, output
    assert sql.read_text() == "select 1  as the_answer\n"


@pytest.mark.skip_if_binaries_missing("sqruff")
def test_sqruff_fix_fixes_sql(tmp_path: Path) -> None:
    sql = tmp_path / "query.sql"
    sql.write_text("select 1  as the_answer\n")
    result = run_tool("sqruff", "fix", str(sql))
    assert result.returncode == 0, result.stdout + result.stderr
    assert sql.read_text() == (_FILES / "clean.sql").read_text()


@pytest.mark.skip_if_binaries_missing("sqruff")
def test_sqruff_fix_fails_on_unfixable_sql(tmp_path: Path) -> None:
    unfixable = "select 1 as x\nfrom t where a=1 and\n"
    sql = tmp_path / "query.sql"
    sql.write_text(unfixable)
    result = run_tool("sqruff", "fix", str(sql))
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "Unparsable section" in output, output
    assert sql.read_text() == unfixable


def test_run_tool_exit_zero_skips_when_tool_truly_missing() -> None:
    # Sanity: --exit-zero path against a guaranteed-missing tool still exits 0.
    # No real tool is involved, so this runs unconditionally (no skip marker).
    result = run_tool("no-such-tool-xyzzy-42", "--exit-zero", str(_FILES / "clean.sh"))
    assert result.returncode == 0


@pytest.mark.skip_if_binaries_missing("ruff")
def test_ruff_check_passes_on_clean_py() -> None:
    result = run_tool("ruff", "check", "--force-exclude", str(_FILES / "clean_py.py"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("ruff")
def test_ruff_format_check_passes_on_clean_py() -> None:
    result = run_tool(
        "ruff", "format", "--check", "--force-exclude", str(_FILES / "clean_py.py")
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("typos")
def test_typos_passes_on_clean_fixture() -> None:
    result = run_tool("typos", str(_FILES / "clean_py.py"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("rumdl")
def test_rumdl_passes_on_clean_md() -> None:
    result = run_tool("rumdl", "check", str(_FILES / "clean.md"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("codespell")
def test_codespell_passes_on_clean_fixture() -> None:
    result = run_tool("codespell", str(_FILES / "clean_py.py"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("mypy")
def test_mypy_passes_on_clean_py() -> None:
    result = run_tool(
        "mypy",
        "--ignore-missing-imports",
        "--scripts-are-modules",
        str(_FILES / "clean_py.py"),
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("yamllint")
def test_yamllint_passes_on_clean_yaml() -> None:
    result = run_tool("yamllint", str(_FILES / "clean.yaml"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("yamlfmt")
def test_yamlfmt_lint_passes_on_clean_yaml() -> None:
    # -lint = check-only (non-zero if the file is not already formatted)
    result = run_tool("yamlfmt", "-lint", str(_FILES / "clean.yaml"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("taplo")
def test_taplo_lint_passes_on_clean_toml() -> None:
    result = run_tool("taplo", "lint", str(_FILES / "clean.toml"))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skip_if_binaries_missing("taplo")
def test_taplo_fmt_check_passes_on_clean_toml() -> None:
    result = run_tool("taplo", "fmt", "--check", str(_FILES / "clean.toml"))
    assert result.returncode == 0, result.stdout + result.stderr
