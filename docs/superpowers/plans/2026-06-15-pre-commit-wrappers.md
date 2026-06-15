# pre-commit-wrappers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable pre-commit hook repository whose hooks run the system-installed (mise-pinned) version of each tool from PATH — never Docker or a from-source compile — with an `--exit-zero` escape hatch.

**Architecture:** A single generic Bash forwarder (`hooks/run-tool.sh`) strips `--exit-zero`, checks the tool is on PATH, and `exec`s it with the remaining args; baked-in defaults live in each hook's `entry` (non-overridable, consumer-extensible). `pin-github-actions.py` is a standalone Python tool ported verbatim from the reference repo. `.pre-commit-hooks.yaml` exposes five hook ids (`actionlint`, `shellcheck`, `gitleaks`, `pin-github-actions`, `system-tool`). The repo dogfoods its own hooks and is tested with one `pytest` runner driving both the shell wrapper (via subprocess) and the Python tool (via importlib).

**Tech Stack:** Bash, Python 3.11+ (stdlib only at runtime), pytest, uv, mise, prek/pre-commit.

**Spec:** `docs/superpowers/specs/2026-06-15-pre-commit-wrappers-design.md`

**Reference repo (source of ported files):** `/Users/pedro.algarvio/projects/me/toolr`

---

## File Structure

```
.pre-commit-hooks.yaml        # hook manifest (consumed by other repos)
hooks/
  run-tool.sh                 # generic forwarder (executable)
  pin-github-actions.py       # python tool, ported verbatim (executable)
README.md
LICENSE                       # already present — do not touch
pyproject.toml                # uv-managed; dev group = pytest; NO build-system
mise.toml                     # pins the tools this repo's own hooks need
.pre-commit-config.yaml       # dogfood: this repo runs its own hooks (repo: local)
.gitignore
tests/
  test_run_tool.py            # drives run-tool.sh via subprocess
  test_pin_github_actions.py  # ported from toolr, _HOOK_PATH repointed
.github/workflows/ci.yml      # mise install + prek run --all-files + pytest
```

---

### Task 1: Project scaffolding (uv + mise + .gitignore)

**Files:**
- Create: `pyproject.toml` (via `uv init --bare`)
- Create: `mise.toml`
- Create: `.gitignore`

- [ ] **Step 1: Initialise the uv project (bare — no package, no build-system)**

Run:
```bash
cd /Users/pedro.algarvio/projects/me/pre-commit-wrappers
uv init --bare --name pre-commit-wrappers \
  --description "Pre-commit hooks that run the system (mise-pinned) tool from PATH — no Docker, no drift"
```
Expected: creates `pyproject.toml` with `[project]` only (no `src/`, no `main.py`, no `[build-system]`).

- [ ] **Step 2: Add pytest and sqlfluff to the dev dependency group**

Run:
```bash
uv add --group dev pytest sqlfluff
```
Expected: `pyproject.toml` gains `[dependency-groups] dev = ["pytest>=...", "sqlfluff>=..."]`; `uv.lock` created. sqlfluff lives in the dev group (not `mise.toml`) because it is a pure-Python tool used only by the hook integration tests — `uv run pytest` syncs it into the `.venv` (which mise activates), so `sqlfluff` is on PATH for the tests but is never installed for normal hook users.

- [ ] **Step 3: Add pytest config to `pyproject.toml`**

Append this block to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 4: Create `mise.toml`**

```toml
[tools]
python = "3.13"
uv = "latest"
prek = "latest"
# These back the pre-commit hooks (run the PATH binary, not Docker / source).
actionlint = "latest"
shellcheck = "latest"
gitleaks = "latest"
# gh resolves Action SHAs for the pin-github-actions hook.
gh = "latest"
# NOTE: sqlfluff is NOT here — it's a pure-Python tool in the uv dev group
# (see Step 2), installed only for the hook integration tests.

[env]
# Auto-create and activate a project virtualenv; uv seeds it with pip.
_.python.venv = { path = ".venv", create = true, uv_create_args = ['--seed'] }

[settings]
python.uv_venv_auto = true
```

- [ ] **Step 5: Create `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 6: Verify the toolchain installs and pytest resolves**

Run:
```bash
mise install
uv run pytest --version
```
Expected: `mise install` provisions the tools; `pytest --version` prints a version (deps auto-synced).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock mise.toml .gitignore
git commit -m "Scaffold uv project + mise toolchain"
```

---

### Task 2: `hooks/run-tool.sh` — generic forwarder (TDD)

**Files:**
- Create: `tests/test_run_tool.py`
- Create: `hooks/run-tool.sh`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_run_tool.py`:
```python
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
    script = (
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$@" > "{log}"\n'
        f"exit {exit_code}\n"
    )
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
    assert result.returncode == 4  # tool ran and failed; --exit-zero only guards a MISSING tool
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_run_tool.py -v`
Expected: FAIL — `hooks/run-tool.sh` does not exist (subprocess raises / non-zero), or collection errors on the missing script.

- [ ] **Step 3: Write `hooks/run-tool.sh`**

```bash
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
```

- [ ] **Step 4: Make it executable**

Run: `chmod +x hooks/run-tool.sh`

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_run_tool.py -v`
Expected: PASS — all 9 tests green.

- [ ] **Step 6: Commit**

```bash
git add hooks/run-tool.sh tests/test_run_tool.py
git commit -m "Add generic run-tool.sh forwarder + tests"
```

---

### Task 3: `hooks/pin-github-actions.py` — ported Python tool + tests

**Files:**
- Create: `hooks/pin-github-actions.py` (copied verbatim from the reference repo)
- Create: `tests/test_pin_github_actions.py` (copied, then 2 lines edited)

- [ ] **Step 1: Copy the hook script verbatim from the reference repo**

Run:
```bash
cp /Users/pedro.algarvio/projects/me/toolr/.pre-commit-hooks/pin-github-actions.py \
   hooks/pin-github-actions.py
chmod +x hooks/pin-github-actions.py
```
Expected: `hooks/pin-github-actions.py` exists, executable, with shebang `#!/usr/bin/env python3`. Do NOT modify its contents — it already implements the `--exit-zero` convention and is stdlib-only.

- [ ] **Step 2: Copy the test file from the reference repo**

Run:
```bash
cp /Users/pedro.algarvio/projects/me/toolr/tests/hooks/test_pin_github_actions.py \
   tests/test_pin_github_actions.py
```

- [ ] **Step 3: Repoint the hook path (the test moved one directory shallower)**

In `tests/test_pin_github_actions.py`, change the two path-setup lines near the top.

Find:
```python
_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_PATH = _REPO_ROOT / ".pre-commit-hooks" / "pin-github-actions.py"
```
Replace with:
```python
_REPO_ROOT = Path(__file__).resolve().parents[1]
_HOOK_PATH = _REPO_ROOT / "hooks" / "pin-github-actions.py"
```
(`parents[2]` → `parents[1]` because the test now lives at `tests/` not `tests/hooks/`; the hooks dir is `hooks/` not `.pre-commit-hooks/`.)

- [ ] **Step 4: Run the ported tests to verify they pass**

Run: `uv run pytest tests/test_pin_github_actions.py -v`
Expected: PASS — all tests green (they stub `gh`/`subprocess` and never touch the network).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS — `test_run_tool.py` + `test_pin_github_actions.py` all green.

- [ ] **Step 6: Commit**

```bash
git add hooks/pin-github-actions.py tests/test_pin_github_actions.py
git commit -m "Port pin-github-actions.py hook + tests from toolr"
```

---

### Task 4: `.pre-commit-hooks.yaml` — the hook manifest

**Files:**
- Create: `.pre-commit-hooks.yaml`

- [ ] **Step 1: Create the manifest**

```yaml
---
# Hooks that run the system-installed (mise-pinned) tool from PATH — no Docker,
# no from-source compile. The tool's version lives in the consumer's mise.toml
# (single source of truth), so it never drifts from a hook's own pin.
# See README.md for usage with prek / pre-commit and mise.

- id: actionlint
  name: Lint GitHub Actions workflow files
  description: Runs system-installed actionlint to lint GitHub Actions workflow files
  entry: hooks/run-tool.sh actionlint
  language: script
  types: [yaml]
  files: ^\.github/workflows/
  minimum_pre_commit_version: 3.0.0

- id: shellcheck
  name: ShellCheck
  description: Static analysis tool for shell scripts
  entry: hooks/run-tool.sh shellcheck
  language: script
  types: [shell]
  exclude: '\.(zsh|fish)$'

- id: gitleaks
  name: Detect hardcoded secrets
  description: Detect hardcoded secrets using Gitleaks
  entry: hooks/run-tool.sh gitleaks git --pre-commit --redact --staged --verbose
  language: script
  pass_filenames: false

- id: pin-github-actions
  name: Pin & verify GitHub Action SHAs
  description: 'Pin GitHub Action uses: refs to commit SHAs and verify existing pins'
  entry: hooks/pin-github-actions.py
  language: script
  files: ^(\.github/(workflows|actions/[^/]+)/.*\.ya?ml|action\.yml)$

- id: sqlfluff-lint
  name: sqlfluff-lint
  description: Lints sql files with `SQLFluff`
  entry: hooks/run-tool.sh sqlfluff lint --processes 0 --disable-progress-bar
  language: script
  types: [sql]
  require_serial: true

- id: sqlfluff-fix
  name: sqlfluff-fix
  description: Fixes sql lint errors with `SQLFluff`
  entry: hooks/run-tool.sh sqlfluff fix --show-lint-violations --processes 0 --disable-progress-bar
  language: script
  types: [sql]
  require_serial: true

- id: system-tool
  name: Run a system tool
  description: Run any PATH-installed tool via run-tool.sh (tool + args supplied by the consumer)
  entry: hooks/run-tool.sh
  language: script
```

Note: there is no `additional_dependencies` on the sqlfluff hooks — `language:
script` runs the PATH `sqlfluff`. Consumers supply sqlfluff (and any
templater/adapter plugins) via `mise use sqlfluff` or, for dbt projects, via
their `uv.lock` project venv. This is documented in the README.

- [ ] **Step 2: Validate the YAML parses**

Run: `uv run python -c "import yaml,sys; yaml.safe_load(open('.pre-commit-hooks.yaml')); print('ok')"`

Note: PyYAML may not be installed. If it errors with `ModuleNotFoundError`, instead run:
```bash
uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('.pre-commit-hooks.yaml')); print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add .pre-commit-hooks.yaml
git commit -m "Add .pre-commit-hooks.yaml manifest (5 hooks)"
```

---

### Task 5: `.pre-commit-config.yaml` — dogfood this repo's own hooks

**Files:**
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Create the dogfood config**

Uses `repo: local` entries that point `entry:` directly at the scripts in this repo (a deliberate, small duplication of the manifest — it avoids a circular `repo:` reference to an unreleased tag).

```yaml
---
minimum_pre_commit_version: 3.0.0
repos:
  - repo: local
    hooks:
      - id: actionlint
        name: Lint GitHub Actions workflow files
        entry: hooks/run-tool.sh actionlint
        language: script
        types: [yaml]
        files: ^\.github/workflows/

      - id: shellcheck
        name: ShellCheck
        entry: hooks/run-tool.sh shellcheck
        language: script
        types: [shell]
        exclude: '\.(zsh|fish)$'

      - id: gitleaks
        name: Detect hardcoded secrets
        entry: hooks/run-tool.sh gitleaks git --pre-commit --redact --staged --verbose
        language: script
        pass_filenames: false

      - id: pin-github-actions
        name: Pin & verify GitHub Action SHAs
        entry: hooks/pin-github-actions.py
        language: script
        files: ^(\.github/(workflows|actions/[^/]+)/.*\.ya?ml|action\.yml)$
```

- [ ] **Step 2: Run the dogfood hooks (excluding pin, which needs gh + a workflow that does not exist yet)**

Run:
```bash
mise install
prek run --all-files --hook-stage pre-commit shellcheck gitleaks
```
Expected: `shellcheck` lints `hooks/run-tool.sh` (clean); `gitleaks` scans staged content (clean). `actionlint`/`pin-github-actions` have no matching files yet — that's fine.

If `prek` is unavailable, substitute `pre-commit run shellcheck gitleaks --all-files`.

- [ ] **Step 3: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "Dogfood: run our own hooks via repo: local"
```

---

### Task 6: `.github/workflows/ci.yml` — CI that installs mise, dogfoods hooks, runs tests

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the workflow with tag refs (to be SHA-pinned in Step 2)**

```yaml
---
name: CI
on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: jdx/mise-action@v3
      - run: mise install
      - name: Run pre-commit hooks (prek)
        env:
          GH_TOKEN: ${{ github.token }}
        run: prek run --all-files --show-diff-on-failure
      - name: Run tests
        run: uv run pytest -v
```

- [ ] **Step 2: SHA-pin the workflow's actions using this repo's own pin tool**

This requires an authenticated `gh` (run `gh auth status`; the hook calls `gh api`).
Run:
```bash
hooks/pin-github-actions.py .github/workflows/ci.yml
```
Expected: the `uses:` lines are rewritten to `owner/repo@<40-char-sha> # <tag>`. Re-run it once more:
```bash
hooks/pin-github-actions.py .github/workflows/ci.yml
```
Expected: exit 0, no further changes (already pinned and verified).

If `gh` is not authenticated in this environment, leave the tag refs and note that the first CI run's `pin-github-actions` hook will fail until they are pinned; pin them in a follow-up before relying on green CI.

- [ ] **Step 3: Lint the workflow locally**

Run:
```bash
prek run --all-files actionlint
```
Expected: `actionlint` passes on `.github/workflows/ci.yml`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "Add CI: mise install + prek run --all-files + pytest"
```

---

### Task 7: `README.md`

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

````markdown
# pre-commit-wrappers

Pre-commit hooks that run the **system-installed** version of each tool —
pinned with [mise](https://mise.jdx.dev) — straight from your `PATH`.

## Why

A normal pre-commit setup pins each tool **twice**: once in
`.pre-commit-config.yaml` (the hook repo's `rev:` or `additional_dependencies`)
and once in `mise.toml` for everything else (CI, local dev, `mise run` tasks).
Those two pins **drift** — bump `mise.toml` to gitleaks 8.x and the upstream
hook silently keeps gating commits with the 7.x it pulled for its own `rev:`.

Running the system binary collapses both into a **single source of truth**:
`mise.toml`. The hook carries no version of its own, so nothing drifts. Bump the
tool in `mise.toml` and the hook, CI, and local dev all move together.

- **No Docker, ever.** These hooks never use `language: docker_image` or
  compile a tool from source. They call the binary already on your `PATH`.
- **`--exit-zero` escape hatch.** Pass `--exit-zero` and a missing tool becomes
  a warning (exit 0) instead of blocking your commit — handy for contributors
  who haven't installed every tool, or for advisory CI.

## Available hooks

| id | tool (must be on PATH) | what it does |
|----|------------------------|--------------|
| `actionlint` | `actionlint` | Lint GitHub Actions workflow files |
| `shellcheck` | `shellcheck` | Static analysis for shell scripts |
| `gitleaks` | `gitleaks` | Scan staged changes for secrets |
| `pin-github-actions` | `gh` | Pin Action `uses:` refs to SHAs and verify existing pins |
| `sqlfluff-lint` | `sqlfluff` | Lint SQL files |
| `sqlfluff-fix` | `sqlfluff` | Auto-fix SQL lint errors |
| `system-tool` | _(you choose)_ | Run any PATH tool via the generic wrapper |

## 1. Install the tools with mise

Add the tools your chosen hooks need to your project's `mise.toml`:

```toml
[tools]
actionlint = "latest"
shellcheck = "latest"
gitleaks = "latest"
gh = "latest"        # only needed for pin-github-actions
```

or per tool on the command line:

```bash
mise use actionlint@latest
mise use shellcheck@latest
mise use gitleaks@latest
mise use gh@latest
```

Then `mise install`. mise's aqua/asdf backends cover all of these.

## 2. Use the hooks with prek (or pre-commit)

Add this repo to your `.pre-commit-config.yaml`, pinned to a release tag:

```yaml
repos:
  - repo: https://github.com/s0undt3ch/pre-commit-wrappers
    rev: v1.0.0   # pin to a released tag; bump deliberately
    hooks:
      - id: actionlint
      - id: shellcheck
      - id: gitleaks
      - id: pin-github-actions
```

Install and run with [prek](https://github.com/j178/prek):

```bash
prek install
prek run --all-files
```

(`pre-commit` works identically — substitute `pre-commit` for `prek`.)

Each hook ships sensible defaults baked into its `entry` (which a consumer
**cannot** override), so they "just work". Anything you add via `args:` is
*appended* — it extends the defaults, it does not replace them.

## 3. The `--exit-zero` escape hatch

Pass `--exit-zero` to any hook and a **missing tool** degrades to a warning
instead of failing the commit. It never hides a real failure from a tool that
did run.

```yaml
      - id: gitleaks
        args: [--exit-zero]
```

## 4. The generic `system-tool` hook

Wrap any PATH tool without a dedicated hook id. You supply the tool name and its
args via `args:` (the first token is the tool name):

```yaml
      - id: system-tool
        alias: shfmt          # distinct name so you can reuse the id
        name: shfmt
        args: [shfmt, -d, -i, "2"]
        types: [shell]
# -> runs: shfmt -d -i 2 <staged shell files>
```

This is also the **trial path** for a new tool: prove it behaves under the
wrapper here, then open a PR promoting it to a first-class dedicated hook.

> **Limitation:** the generic hook needs at least one arg or filename. A bare,
> argument-less command (`args: [mytool]` with `pass_filenames: false`) no-ops.

## 5. sqlfluff (and the "no `additional_dependencies`" rule)

`sqlfluff-lint` / `sqlfluff-fix` run the `sqlfluff` already on your PATH. Unlike
the upstream `sqlfluff/sqlfluff` hooks, **there is no `additional_dependencies`**
— `language: script` ignores it. You provide sqlfluff and any plugins yourself,
which keeps a single source of truth:

- **Plain SQL:** `mise use sqlfluff` (mise's pipx backend).
- **dbt projects:** add `sqlfluff`, `sqlfluff-templater-dbt`, and your dbt
  adapter to the project's Python dependencies (`uv.lock`) — the same env you
  run dbt with. mise activates that venv, so the right `sqlfluff` is on PATH.
  No separate hook venv, no second pin to drift.

```yaml
      - id: sqlfluff-lint
      - id: sqlfluff-fix
```

## Development

```bash
mise install          # provision python, uv, prek, and the tools
uv run pytest         # run the test suite
prek run --all-files  # run this repo's hooks against itself
```
````

- [ ] **Step 2: Lint the README is not broken (sanity check the repo builds)**

Run: `uv run pytest -q`
Expected: PASS (README has no executable effect, but confirms nothing regressed).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Add README: rationale, mise install, prek usage, escape hatch"
```

---

### Task 8: Hook integration tests against real tools + sample files

Drives each real tool through `run-tool.sh` on a clean fixture, skipping when
the tool is not on PATH. Proves the actual hooks work end-to-end (the Task 2
tests use fake tools only).

**Files:**
- Create: `tests/files/clean_workflow.yml`
- Create: `tests/files/clean.sh`
- Create: `tests/files/clean.sql`
- Create: `tests/files/.sqlfluff`
- Create: `tests/test_hooks_integration.py`

- [ ] **Step 1: Create the clean GitHub Actions workflow fixture**

`tests/files/clean_workflow.yml`:
```yaml
---
name: sample
on:
  push:
    branches: [main]
jobs:
  noop:
    runs-on: ubuntu-latest
    steps:
      - run: echo "hello"
```

- [ ] **Step 2: Create the shellcheck-clean script fixture**

`tests/files/clean.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

echo "hello, world"
```

- [ ] **Step 3: Create the sqlfluff config + a SQL fixture**

`tests/files/.sqlfluff`:
```ini
[sqlfluff]
dialect = ansi
```

`tests/files/clean.sql` (initial content — Step 5 makes it lint-clean):
```sql
select 1 as the_answer
```

- [ ] **Step 4: Write the integration tests**

`tests/test_hooks_integration.py`:
```python
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


@pytest.mark.skipif(shutil.which("sqlfluff") is None, reason="sqlfluff not on PATH")
def test_sqlfluff_lint_passes_on_clean_sql() -> None:
    result = run_tool(
        "sqlfluff", "lint", "--processes", "0", "--disable-progress-bar",
        str(_FILES / "clean.sql"),
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("actionlint") is None, reason="actionlint not on PATH")
def test_run_tool_exit_zero_skips_when_tool_truly_missing() -> None:
    # Sanity: --exit-zero path against a guaranteed-missing tool still exits 0.
    result = run_tool("no-such-tool-xyzzy-42", "--exit-zero", str(_FILES / "clean.sh"))
    assert result.returncode == 0
```

- [ ] **Step 5: Make the SQL fixture lint-clean by running the tool itself**

Run:
```bash
mise install
sqlfluff fix --processes 0 --disable-progress-bar tests/files/clean.sql
sqlfluff lint --processes 0 --disable-progress-bar tests/files/clean.sql
```
Expected: `fix` normalises the file (if needed); `lint` then exits 0. If `lint`
still reports violations, apply its suggestions until it is clean. Commit the
clean version.

- [ ] **Step 6: Run the integration tests**

Run: `uv run pytest tests/test_hooks_integration.py -v`
Expected: PASS (or SKIP for any tool not installed locally; all PASS under CI).

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS — unit + integration tests green.

- [ ] **Step 8: Commit**

```bash
git add tests/files tests/test_hooks_integration.py
git commit -m "Add hook integration tests against real tools + sample files"
```
(sqlfluff was added to the dev group in Task 1, so `pyproject.toml`/`uv.lock`
are already committed.)

---

### Task 9: Final verification

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -v`
Expected: PASS — both test modules green.

- [ ] **Step 2: Full dogfood run**

Run: `prek run --all-files --show-diff-on-failure`
Expected: all hooks pass (`pin-github-actions` requires authenticated `gh`; if unavailable locally, run the other four and note pin runs in CI).

- [ ] **Step 3: Confirm executables and layout**

Run:
```bash
test -x hooks/run-tool.sh && test -x hooks/pin-github-actions.py && echo "executables ok"
ls .pre-commit-hooks.yaml README.md mise.toml pyproject.toml .pre-commit-config.yaml
```
Expected: `executables ok` and all files listed.
