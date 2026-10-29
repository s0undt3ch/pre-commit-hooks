# CLAUDE.md

Read README.md for what this repo is and how the hooks work.

## Hook rules

- Every hook runs the tool already on `PATH`. Don't use `language: docker_image`,
  `additional_dependencies`, or a hook that builds the tool from source. The
  version lives only in the consumer's `mise.toml` or lockfile.
- Bake a hook's defaults into its `entry`. Consumers can't override `entry`, and
  their `args:` are appended to it.
- `docs/superpowers/` holds the original design spec and plan. It is a record of
  how the repo started, not current documentation, and the linters skip it.
  Don't update it to match the code.

## Adding a hook

1. Add the entry to `.pre-commit-hooks.yaml` with
   `entry: hooks/run-tool.sh <tool> [default args]` and `language: script`. Copy
   the `files:` and `types:` patterns from the tool's upstream hook rather than
   inventing them.
2. Pin the tool for this repo's tests. Binary tools go in `mise.toml`. Pure-Python
   tools go in the `dev` group of `pyproject.toml`, then run `uv lock`.
3. Add a clean fixture to `tests/files/` and an integration test to
   `tests/test_hooks_integration.py`. Skip the test when the tool isn't on `PATH`.
4. Add a row to the README hook table. Add a README section if the hook needs
   setup or has options worth knowing.
5. If the hook applies to this repo's own files, add it to
   `.pre-commit-config.yaml` too.

## Workflows and pins

- This repo lints its own workflows with jactionlint's default profile. Each
  workflow sets `permissions:` at the top level, read-only or `{}`. A job that
  needs write access gets it in its own `permissions:`. Each workflow also sets
  a `concurrency` group and `timeout-minutes` on every job. Each
  `actions/checkout` step sets `persist-credentials: false`.
- Renovate bumps the action pins and the tools in `mise.toml` weekly. Bump one by
  hand only when it is broken.
- `pin-github-actions` fails when a floating tag such as `v5` moves to a new
  commit. Before updating the pin, confirm the tag's new target is a real
  upstream release (`gh api repos/<owner>/<repo>/git/ref/tags/<tag>`).
- Keep a `workflow = "..."` option that `mise use` writes to a tool in
  `mise.toml`. It pins which upstream workflow must have signed the release.

## Verifying a change

Run both before opening a PR:

```bash
uv run pytest
prek run --all-files
```

## Releasing

Consumers pin a release tag in their `rev:`, so each tag is a published
artefact. Pushing a `v*` tag runs `.github/workflows/release.yml`, which creates
the GitHub release with auto-generated notes.

- Pick the version by semver against the last tag (`git tag --sort=-v:refname`):
  - patch: fixes only;
  - minor: new hooks or options, and nothing removed or renamed;
  - major: a hook id removed or renamed, or a default changed in a way that
    breaks existing configs.
- Release from an up-to-date `main` with a clean working tree.
- Use a signed, annotated tag, never a lightweight one:

  ```bash
  git tag -s vX.Y.Z -m "vX.Y.Z"
  git tag -v vX.Y.Z
  git push origin vX.Y.Z
  ```

  The signature records who cut the release and stops anyone repointing the tag
  unnoticed. Tags up to and including `v1.4.0` are lightweight. Leave them
  as they are, because consumers already pin them.
- After pushing, check that the `Release` workflow run succeeded and the
  release exists:
  `gh release view vX.Y.Z --repo s0undt3ch/pre-commit-hooks`.
