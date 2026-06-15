# pre-commit-wrappers — Design

**Date:** 2026-06-15
**Status:** Approved (pending spec review)

## Purpose

A reusable pre-commit hook repository whose hooks run the **system-installed**
version of each tool — pinned via [mise](https://mise.jdx.dev) in the consuming
repo — instead of pulling a Docker image or compiling the tool from source on a
cold cache. Every hook accepts an `--exit-zero` escape hatch so that a missing
tool degrades to a warning (exit 0) rather than blocking the commit.

### Why this repo exists — one version, no drift

The core problem it solves is **version drift**. A conventional pre-commit setup
pins each tool *twice*: once in `.pre-commit-config.yaml` (the hook repo's
`rev:`, or `additional_dependencies`) and once in `mise.toml` for every other
context that uses the tool (CI, local dev, `mise run` tasks). Those two pins
drift apart: bump `mise.toml` to gitleaks 8.x and the upstream hook silently
keeps gating commits with the 7.x it compiled/pulled for its own `rev:` — so the
version that guards your commits is no longer the version you actually ship and
run everywhere else.

Running the **system binary** collapses both pins into a single source of truth:
`mise.toml`. The hook carries no version of its own, so there is nothing to
drift. Bump the tool in `mise.toml` and the hook, CI, and local dev all move in
lockstep automatically.

### No Docker — by design

This repository exists specifically to **avoid Docker**. Upstream hooks such as
`koalaman/shellcheck-precommit` (`language: docker_image`) need a Docker daemon
and a registry pull — unavailable on hardened CI runners and wasteful when the
exact pinned binary is already on `PATH`. Others (`rhysd/actionlint`,
`gitleaks/gitleaks`) default to `language: golang`, which compiles the tool from
source through the Go toolchain on every cold cache. None of the hooks here use
Docker or source-compilation; they call the system binary directly. This is
stated plainly in the README.

## Components

### 1. `run-tool.sh` — generic forwarder (shell hooks)

A single Bash script (`hooks/run-tool.sh`) backing every thin "run the system
binary" hook. Invoked as:

```
hooks/run-tool.sh <tool> [default-args...]   # + consumer args + filenames (appended by pre-commit)
```

Behaviour:

1. The **first positional argument** is the tool name.
2. Scan **all remaining arguments**; drop any literal `--exit-zero` token
   (wherever it appears) and set an `exit_zero` flag. Every other argument is
   forwarded verbatim, in order.
3. If `command -v <tool>` fails (tool not on `PATH`):
   - `--exit-zero` given → print a warning to stderr and `exit 0`.
   - otherwise → print an error to stderr naming the tool and suggesting it be
     installed (e.g. via mise) and `exit 1`.
4. If **no forwarded arguments remain** (e.g. a file-based hook that prek
   filtered down to nothing) → `exit 0` quietly without invoking the tool.
5. Otherwise `exec "<tool>" "${rest[@]}"` so the tool's own exit status
   propagates unchanged.

`set -euo pipefail`. `--exit-zero` is owned by this convention and only ever
affects the **missing-tool** case — it never suppresses a real non-zero exit
from a tool that did run.

### 2. `pin-github-actions.py` — standalone Python tool

Ported as-is from the reference repo (`toolr/.pre-commit-hooks/pin-github-actions.py`).
It pins GitHub Action `uses:` refs to commit SHAs and verifies already-pinned
refs against their `# <tag>` comment, using the system `gh` CLI. It already
implements the `--exit-zero` convention (downgrades a missing `gh` from a hard
error to a warning + exit 0). Stdlib only at runtime. Not a forwarder — it owns
its own logic, so it is its own script rather than going through `run-tool.sh`.

### 3. `.pre-commit-hooks.yaml` — hook manifest

Defines seven hook ids, all `language: script`.

**Default tool args go in `entry`, never in `args`.** pre-commit lets a consumer
override a hook's `args:` (and the override *replaces* it wholesale), but it does
**not** let a consumer override `entry`. pre-commit builds the command as
`entry` (fixed by us) + `args` (consumer-settable, empty by default) + filenames.
So baking `git --pre-commit --redact --staged --verbose` into `gitleaks`'s
`entry` makes those defaults **non-overridable yet still extensible**: a consumer
who sets `args: [--exit-zero, --report-path, x.json]` gets them *appended* after
the defaults, not in place of them. (This mirrors upstream `gitleaks/gitleaks`,
whose own manifest bakes the same four flags into `entry`.) Putting defaults in
`args:` instead would let a consumer silently drop them — so we never do that.

`run-tool.sh` then strips `--exit-zero` from anywhere in the resulting line and
forwards the rest. This is why no per-tool thin wrappers are needed: the
generic wrapper + defaults-in-`entry` already gives non-overridable,
consumer-extensible defaults.

Each hook's `name`, `description`, `types`, `files`, and `pass_filenames` mirror
the corresponding upstream hook so the hooks read familiarly in a consumer's
output — only the `entry` (indirection through `run-tool.sh`) and `language:
script` differ.

| id | entry | name / description | other fields |
|----|-------|--------------------|--------------|
| `actionlint` | `hooks/run-tool.sh actionlint` | `Lint GitHub Actions workflow files` / `Runs system-installed actionlint to lint GitHub Actions workflow files` | `types: [yaml]`, `files: ^\.github/workflows/` |
| `shellcheck` | `hooks/run-tool.sh shellcheck` | `ShellCheck` / `Static analysis tool for shell scripts` | `types: [shell]`, `exclude: '\.(zsh\|fish)$'` |
| `gitleaks` | `hooks/run-tool.sh gitleaks git --pre-commit --redact --staged --verbose` | `Detect hardcoded secrets` / `Detect hardcoded secrets using Gitleaks` | `pass_filenames: false` |
| `pin-github-actions` | `hooks/pin-github-actions.py` | `Pin & verify GitHub Action SHAs` / `Pin GitHub Action uses: refs to commit SHAs and verify existing pins` | `files:` workflows / composite actions / root `action.yml` |
| `sqlfluff-lint` | `hooks/run-tool.sh sqlfluff lint --processes 0 --disable-progress-bar` | `sqlfluff-lint` / `Lints sql files with` `SQLFluff` | `types: [sql]`, `require_serial: true` |
| `sqlfluff-fix` | `hooks/run-tool.sh sqlfluff fix --show-lint-violations --processes 0 --disable-progress-bar` | `sqlfluff-fix` / `Fixes sql lint errors with` `SQLFluff` | `types: [sql]`, `require_serial: true` |
| `system-tool` | `hooks/run-tool.sh` | `Run a system tool` / `Run any PATH-installed tool via run-tool.sh (tool name + args supplied by the consumer)` | no defaults; consumer supplies everything |

### 4. `system-tool` — generic escape-hatch hook

A manifest entry with **no tool baked into `entry`** — just
`entry: hooks/run-tool.sh`. The consumer supplies the tool name and its args via
the consumer-settable `args:` field, which pre-commit appends after `entry`; so
the first `args` token lands as `run-tool.sh`'s tool-name argument:

```yaml
# consumer .pre-commit-config.yaml
- id: system-tool
  alias: shfmt                     # distinct name so it can be used more than once
  name: shfmt
  args: [shfmt, -d, -i, "2"]       # tool + args; --exit-zero may appear anywhere
  types: [shell]
# -> run-tool.sh shfmt -d -i 2 <files>
```

This needs **no new code** — it reuses `run-tool.sh` verbatim and inherits the
strip-`--exit-zero` / PATH-check / forward behaviour and its tests. It lets a
consumer wrap *any* PATH tool without this repo shipping a dedicated hook, and
the same id can be reused several times via different `alias:` + `args:`.

It also serves as the **prototyping / trial path for new tools**: before opening
a PR to add a dedicated hook here, a contributor can wrap the candidate tool
through `system-tool` in their own config and confirm it behaves correctly under
`run-tool.sh` (PATH resolution, `--exit-zero`, arg/filename forwarding). If it
works and is broadly useful, *then* promote it to a first-class dedicated hook
via a PR. So the dedicated hooks and the generic hook are two ends of the same
mechanism — `system-tool` is where a tool starts; a named hook id is where it
lands once proven.

**Limitation (documented):** because `run-tool.sh` exits 0 when no arguments
remain after the tool name, the generic hook needs at least one arg or filename.
A bare argument-less command (`args: [mytool]` with `pass_filenames: false`)
would no-op. Every real use passes a subcommand/flag or filenames, so this is a
non-issue in practice — but it is called out in the README.

Upstream-matching details:

- **`actionlint`** mirrors `rhysd/actionlint`'s `actionlint-system` hook
  (name/description/`types`/`files`). The repo also sets
  `minimum_pre_commit_version: 3.0.0`, as upstream does.
- **`shellcheck`** mirrors `koalaman/shellcheck-precommit`'s description and
  `types: [shell]`. Upstream **version-stamps** its name (`ShellCheck v0.11.0`);
  we deliberately drop the version — running the system binary means the name
  must not assert a version it doesn't control (that would be its own kind of
  drift). The `exclude: '\.(zsh\|fish)$'` is our addition (shellcheck can't parse
  zsh/fish), carried from the reference repo.
- **`gitleaks`** matches `gitleaks/gitleaks`'s `entry`, `name`, `description`,
  and `pass_filenames: false` exactly.
- **`pin-github-actions`** is bespoke (no upstream); name/description taken from
  the reference repo's local hook.
- **`sqlfluff-lint` / `sqlfluff-fix`** mirror `sqlfluff/sqlfluff`'s entries
  verbatim (including `--processes 0 --disable-progress-bar`, and `fix`'s
  `--show-lint-violations`), `types: [sql]`, and `require_serial: true`.

  **No `additional_dependencies` — by design.** The upstream hooks use
  `language: python` and rely on `additional_dependencies` (e.g.
  `sqlfluff-templater-dbt`, a dbt adapter) to build sqlfluff a private venv.
  Our `language: script` hooks run whatever `sqlfluff` is **on PATH**, so that
  mechanism does not apply — and that is the point. The consumer provides
  `sqlfluff` (and any templater/adapter plugins) through their own environment:
  - **Plain SQL:** `mise use sqlfluff` (mise's `pipx` backend) is enough.
  - **dbt projects:** sqlfluff, `sqlfluff-templater-dbt`, and the dbt adapter are
    already the project's Python dependencies pinned in `uv.lock` (the same deps
    used to run dbt). mise activates that venv, so the correct `sqlfluff` is on
    PATH automatically. `uv.lock` is the single source of truth — exactly the
    anti-drift property `mise.toml` provides for the binary tools, with no
    second pin in a hook's `additional_dependencies` to fall out of sync.

  This repo does **not** dogfood the sqlfluff hooks (it contains no SQL); they
  are shipped and documented only.

## Repository layout

```
.pre-commit-hooks.yaml        # hook manifest (consumed by other repos)
hooks/
  run-tool.sh                 # generic forwarder (executable, +x)
  pin-github-actions.py       # python tool (executable, +x)
README.md
LICENSE                       # already present
pyproject.toml                # dev tooling (pytest) via uv; runtime is stdlib-only
mise.toml                     # dogfood: pins the tools this repo's own hooks need
.pre-commit-config.yaml       # dogfood: this repo runs its own hooks
tests/
  test_pin_github_actions.py  # ported verbatim, _HOOK_PATH repointed
  test_run_tool.py            # new — drives run-tool.sh via subprocess
.github/workflows/ci.yml      # mise install + prek run --all-files + pytest
```

All hook scripts live under `hooks/`, so manifest `entry:` paths are
`hooks/run-tool.sh <tool> …` and `hooks/pin-github-actions.py`.

## Testing

One test runner — `uv run pytest` — covers both the Python tool and the shell
wrapper, so CI has a single test step and the repo needs no second test
framework (no bats/shellspec, no extra mise entry).

### `pin-github-actions.py`

`tests/test_pin_github_actions.py` is the reference suite copied over, with
`_HOOK_PATH` repointed at this repo's `hooks/pin-github-actions.py`. It loads the
standalone script via `importlib.util.spec_from_file_location` and never touches
the network: per-line `verify_action_line` tests inject a fake resolver;
`process_file` / cache tests stub `subprocess.run`; `main()` tests monkeypatch
`check_gh_cli`. All existing cases carry over unchanged (doctored SHA, repointed
tag, transient-vs-404 classification, memoisation, missing-gh hard error,
`--exit-zero` softening).

### `run-tool.sh`

`tests/test_run_tool.py` drives the **real** script through `subprocess`. A
fixture builds a `tmp_path/bin` containing tiny fake executables (a stub that
records its argv to a file and exits with a chosen code), prepends it to `PATH`,
and runs `run-tool.sh` under that environment. For missing-tool cases `PATH` is
pointed at a directory without the tool.

| Test | Asserts |
|------|---------|
| tool present, exits 0 | wrapper exits 0; forwards args verbatim and in order |
| tool present, exits 3 | wrapper propagates exit 3 |
| `--exit-zero` + tool present that fails | tool still runs; its non-zero code propagates |
| `--exit-zero` stripped | fake tool's recorded argv contains no `--exit-zero` |
| tool missing, no `--exit-zero` | exit 1; stderr names the tool / suggests installing it |
| tool missing, `--exit-zero` | exit 0; warning on stderr |
| only tool name, no forwarded args | exit 0; tool never invoked |
| default args + filenames | `run-tool.sh faketool a b` forwards `a b` in order |

### Hook integration tests (real tools)

`tests/test_run_tool.py` uses **fake** tools. A second module,
`tests/test_hooks_integration.py`, drives the **real** tools through
`run-tool.sh` against clean fixtures under `tests/files/` (a valid workflow
YAML, a shellcheck-clean script, an ANSI-clean SQL file + `tests/files/.sqlfluff`),
each `@pytest.mark.skipif` the tool is absent from PATH. The binary tools
(actionlint, shellcheck) come from `mise.toml`; `sqlfluff` is a **uv dev-group**
dependency (pure Python, installed only for tests via `uv run pytest`, never for
normal hook users). A contributor missing a tool skips that test; CI installs
everything and runs them all.

## Dogfooding & CI

- **`mise.toml`** pins the tools this repo's own hooks need so the README's
  install instructions are exercised, not aspirational: `python`, `uv`, `prek`,
  `actionlint`, `shellcheck`, `gitleaks`, and `gh` (for `pin-github-actions`).
- **`.pre-commit-config.yaml`** wires this repo's hooks against itself via
  `repo: local` entries that point `entry:` directly at `hooks/run-tool.sh` and
  `hooks/pin-github-actions.py` (mirroring the four manifest hooks), so the wrapper,
  the workflow YAML, and the shell scripts are all linted/scanned by the very
  hooks being shipped. A small, deliberate duplication of the manifest entries —
  it keeps the dogfood self-contained without a circular `repo:` reference to an
  unreleased tag.
- **`.github/workflows/ci.yml`** installs mise (`jdx/mise-action`), runs
  `mise install`, then `prek run --all-files` and `uv run pytest`. The
  `pin-github-actions` hook needs `gh` auth, so the job exports
  `GH_TOKEN: ${{ github.token }}`. All `uses:` refs in this workflow are
  themselves SHA-pinned so the dogfooded `pin-github-actions` hook passes.

## README contents

1. What & why — **one version, no drift** (single source of truth in
   `mise.toml`), system tools, **no Docker**, `--exit-zero` escape hatch.
2. Available hooks table (id → tool → what it needs on `PATH`).
3. **Installing the tools with mise** — per-tool `mise use` lines plus a
   copy-paste `[tools]` block for `mise.toml`.
4. **Using the hooks with prek (and pre-commit)** — a `repos:` snippet pinned to
   a `rev:` release tag, with a note on choosing/upgrading the tag.
5. **The `--exit-zero` escape hatch** — when and why to use it (tool-less or
   gh-less contributors; advisory/best-effort runs), shown as per-hook `args:`.
6. **The generic `system-tool` hook** — wrap any PATH tool yourself; includes the
   "trial a tool before proposing a dedicated hook" workflow and the
   needs-at-least-one-arg limitation.

## Out of scope (YAGNI)

- Per-tool binary-path environment overrides (e.g. `ACTIONLINT_BIN`).
- A shared shell library (ruled out — the repo deliberately mixes Python and
  shell, so a shell lib cannot span both, and the only shared shell logic lives
  in the single `run-tool.sh` already).
- Wrapping tools not yet in use.
- **Terraform and Go hooks — deferred (not rejected).** mise (incl. its aqua
  backend) can install `terraform`/`tflint`/`golangci-lint`/`go`, and the
  forwarder-compatible hooks (`terraform fmt -check -diff -recursive`,
  `tflint --recursive`, `go vet ./...`, `go build ./...`, `golangci-lint run`,
  all `pass_filenames: false`) would slot into `run-tool.sh` cleanly. The ones
  that do **not** fit — `terraform validate` (needs `init` + per-module logic)
  and `gofmt` / `go mod tidy` (need "would-change" wrapper logic) — are the
  reason upstream ships bespoke per-tool scripts, which is exactly what the
  single-wrapper design avoids. Revisit the forwarder-compatible subset in a
  follow-up once the core four hooks ship.
```
