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
| `shfmt` | `shfmt` | Format shell scripts (write in place) |
| `gitleaks` | `gitleaks` | Scan staged changes for secrets |
| `pin-github-actions` | `gh` | Pin Action `uses:` refs to SHAs and verify existing pins |
| `ruff-check` | `ruff` | Lint Python (Ruff) |
| `ruff-format` | `ruff` | Format Python (Ruff) |
| `typos` | `typos` | Source-code spell check |
| `rumdl` | `rumdl` | Lint Markdown |
| `rumdl-fmt` | `rumdl` | Format Markdown |
| `codespell` | `codespell` | Spell check text files |
| `mypy` | `mypy` | Static type-check Python |
| `uv-lock` | `uv` | Keep uv.lock in sync with pyproject |
| `sqlfluff-lint` | `sqlfluff` | Lint SQL files |
| `sqlfluff-fix` | `sqlfluff` | Auto-fix SQL lint errors |
| `yamllint` | `yamllint` | Lint YAML files |
| `yamlfmt` | `yamlfmt` | Format YAML files |
| `system-tool` | *(you choose)* | Run any PATH tool via the generic wrapper |

## 1. Install the tools with mise

Add the tools your chosen hooks need to your project's `mise.toml`:

```toml
[tools]
actionlint = "latest"
shellcheck = "latest"
gitleaks = "latest"
gh = "latest"        # only for pin-github-actions (also run `gh auth login`)
```

or per tool on the command line:

```bash
mise use actionlint@latest
mise use shellcheck@latest
mise use gitleaks@latest
mise use gh@latest
```

Then `mise install`. mise's aqua/asdf backends cover all of these.

> **PATH note:** the hooks resolve each tool from `PATH`. Make sure mise is
> activated in your shell (`mise activate`, the usual setup) — or that mise's
> shims directory is on `PATH` — so `prek`/`pre-commit` can find the
> mise-managed binaries when they run the hooks.

## 2. Use the hooks with prek (or pre-commit)

Add this repo to your `.pre-commit-config.yaml`, pinned to a release tag:

```yaml
repos:
  - repo: https://github.com/s0undt3ch/pre-commit-hooks
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
        alias: taplo          # distinct name so you can reuse the id
        name: taplo
        args: [taplo, lint]
        types: [toml]
# -> runs: taplo lint <staged TOML files>
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
  adapter to the project's Python dependency group (`uv.lock`) — the same env
  you run dbt with. `uv` installs them into the venv mise activates, so the
  right `sqlfluff` is on PATH. No separate hook venv, no second pin to drift.

```yaml
      - id: sqlfluff-lint
      - id: sqlfluff-fix
```

The same principle applies across all hooks: `ruff`, `typos`, `rumdl`, `shfmt`,
and `yamlfmt` (Go binaries) are binary tools managed via `mise` (add them to
your `mise.toml`), while the Python tools `codespell`, `mypy`, `sqlfluff`, and
`yamllint` come from your own dependency group (e.g. `uv.lock`) — none of these
hooks use `additional_dependencies`.

## Development

```bash
mise install          # provision python, uv, prek, and the binary tools
uv run pytest         # run the test suite
prek run --all-files  # run this repo's hooks against itself
```

The integration tests also exercise `sqlfluff`, which is a `uv` **dev-group**
dependency (not in `mise.toml`) — `uv run pytest` installs it into the venv that
mise activates, so it is on `PATH` for the tests but never for normal hook users.
