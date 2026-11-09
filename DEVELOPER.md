# Developer Guide

This guide covers everyday contributor workflows: setup, the dev loop, and releases.
For one-off tasks (extending the CLI, adding skills, updating passthrough tools), see
the linked docs.

## Overview

Asta is a CLI-first package (`src/asta/`) with three Claude Code plugins
(`plugins/asta-tools`, `plugins/asta-flows`, `plugins/asta-dev`). The CLI is a
thin Click wrapper around stdlib-only core API clients; the plugins ship the skills
and hooks that drive agents to call the CLI. Read the source tree directly for the
current layout — `pyproject.toml` is the source of truth for build config.

Design rules worth knowing before you change code:

- Core API clients (`asta.literature.client`, `asta.papers.client`) stay stdlib-only.
- Click commands stay thin — logic belongs in the client classes.
- New external-tool integrations go through the passthrough system
  (`asta.utils.passthrough` + `passthrough.conf`), not bespoke wrappers.

One directory is *not* this repo's own CI:
`.github/workflows/workspace-quarto-site.yml` is a published reusable workflow
(`workflow_call`-only) for the research projects the `workspace` skill
scaffolds — GitHub mandates the `.github/workflows/` path for reusable
workflows, so it can't live with the skill. Maintain it together with
`plugins/asta-tools/skills/workspace/` (its `assets/docs.yml` stub and
`assets/Makefile` `check` target form one contract with it).

PRs from forks and Dependabot-triggered PR runs get read-only tokens, so they
still build and check the site but skip the preview deploy and its cleanup. A
`No preview (fork PR)` or `No preview (Dependabot)` check explains why in a
warning and job summary, and how to get a preview: push the changes to a branch
in the repository and open a PR from that branch. A `workflow_dispatch` on
the default branch publishes main like a push; on another branch it only
builds. All other events deploy as before.

## Development Setup

Prerequisites: Python 3.11+, `uv`, `make`, and Node.js 20+ / `npx`
(skill-discovery tests are skipped if `npx` is missing).

```bash
git clone https://github.com/allenai/asta-plugins.git
cd asta-plugins
make install
```

`make install` creates `.venv/bin/asta` as an editable install — Python changes are
picked up immediately. Run `make help` to see every available target.

To use the dev `asta` from other directories, either invoke
`/path/to/asta-plugins/.venv/bin/asta` directly or activate `.venv`. For coding
agents that invoke bare `asta`, add a shell alias that prepends the venv to `PATH`:

```bash
alias claude-asta='PATH="/path/to/asta-plugins/.venv/bin:$PATH" claude --plugin-dir /path/to/asta-plugins/plugins/asta-tools'
```

If a global `asta` plugin is installed, disable it via Claude Code settings while
developing with `--plugin-dir` to avoid loading skills twice.

**What needs a reinstall:**

| Changed                          | Action                                          |
|----------------------------------|-------------------------------------------------|
| Python files under `src/asta/`   | None — editable install                         |
| `pyproject.toml` (deps, scripts) | `make install`                                  |
| Skills or hooks under `plugins/` | Restart your `claude-asta` session              |

## Dev Loop

```bash
make check     # format-check + lint + unit tests — run before every commit
make ci        # full CI: format-check + lint + all tests + skill validation
make test      # all tests (also: test-unit, test-integration, test-coverage)
make format    # auto-fix formatting
```

`make ci` is what GitHub Actions runs. Get it green before opening a PR.

### PR checklist

- One feature/fix per PR; include tests.
- Update `CHANGELOG.md`.
- Update README.md if user-visible behavior changes.
- `make ci` passes.

## Release Process

The version lives in three places:

- `src/asta/__init__.py` — `__version__`
- `pyproject.toml` — `version`
- `.claude-plugin/marketplace.json` — `plugins[].version`

`make set-version` keeps them in sync; `make push-version-tag` enforces it.

**Every release:**

1. `make set-version VERSION=x.y.z`
2. `git diff` — sanity-check the version bump.
   When introducing an Overleaf sync format, verify `FORMAT_RELEASE` in
   `src/asta/commands/overleaf.py` names the first release shipping its reader.
   The initial format-aware release is planned as 0.116.0; if that changes,
   update the constant, `docs/overleaf-sync.md`, and the workspace developer and
   recovery guides together. Keep this hint unchanged in later compatible
   releases. See [the compatibility contract](docs/overleaf-sync.md#shared-format-and-releases).
3. `make ci` — must be green.
4. Commit and push the version bump:
   ```bash
   git add -A && git commit -m "chore: bump version to x.y.z" && git push
   ```
5. `make push-version-tag` — verifies all three version files match and that
   `HEAD` is on `origin/main`, then waits for the `Docker` workflow run on that
   commit to succeed (`scripts/wait-for-main-image.sh`, needs `gh`) before it
   creates and pushes the git tag. It exits without tagging if that run failed
   or none exists. Every `main` push publishes run-specific candidates
   (`ghcr.io/allenai/asta:sha-<commit>-run-<id>-attempt-<n>` and `…-tex`) and
   smoke-tests them by digest; candidates never move `:latest`. The tag does not
   rebuild: `docker.yml` promotes the validated candidate digests to `:<tag>` /
   `:<tag>-tex`, and a final `vX.Y.Z` tag (not `-rc.N`) then moves `:latest` /
   `:latest-tex` to the highest final release. Promotion reads the candidate
   run's artifacts, so tag within the repository's artifact-retention window.
6. *(Future)* Publish to PyPI: `make publish` (or `make publish-test` for
   TestPyPI).
7. *(Future)* Create a GitHub release from the tag for human-readable notes.
   This is bookkeeping only — the Docker image is already published by step 5, so
   a release is not a prerequisite for anything.
8. Wait for the demo preview refresh on PR #281 (`example-demo-pr`). After a
   final release is promoted, `docker.yml` rebuilds that branch from the same
   highest published final release plus `examples/workspace-demo.patch`, then
   explicitly dispatches Example site with `preview-pr=281`. This uses
   `GITHUB_TOKEN` without an extra secret; a token-created push alone would not
   start unattended PR checks. Keep the existing demo PR open as a draft and
   never merge it. The patch is the only source of its sample edit; do not merge
   main into the demo branch or maintain another copy by hand. A patch that no
   longer applies fails the release's demo job with the patch path in the error.

If `push-version-tag` reports a version mismatch, rerun `make set-version` to
resync — don't hand-edit one file.

Paper previews use the release's `:<tag>-tex` image when the reusable workflow
is pinned to a `v*` tag. Branch and SHA refs use mutable `:latest-tex` with a
warning; pin a release tag when the toolchain must match the workflow release.
The pull retries for one minute to allow tag promotion to finish, then records
a paper-build failure without blocking the rest of the site. If promotion is
still running or failed, retry after the release's Docker workflow succeeds.
This reusable workflow targets GitHub.com; its `job.workflow_*` identity
context is unavailable on GitHub Enterprise Server. Paper builds and project
`paper-preview.sh` overrides run offline as the host UID/GID, without a passwd
entry. Overrides must use the fetched history and local files, and must not
fetch dependencies or require `whoami`/Git author identity. The image's only
TeX is the full TeX Live 2026 install.

## Specific Workflows

- **Extending the CLI** (commands, API endpoints, dependencies, passthrough tools) — [docs/cli-commands.md](docs/cli-commands.md)
- **Authoring skills and hooks** — [docs/plugins.md](docs/plugins.md)
- **Docker image (build, manual test, troubleshooting)** — [docs/docker.md](docs/docker.md)

The public example also publishes `/demo/what-changed.html` on each main build.
`scripts/build-workspace-demo.py` applies `examples/workspace-demo.patch` in a
fresh shared clone and runs the checkout's CLI with the TeX toolchain. The
example's existing after-render artifact command includes that report in the
normal Pages artifact; it adds no publishing workflow or credential. A PR that
changes the rendered example builds the site and demo once, on x86, through the
shared site workflow. The demo PR already contains the patch, so its ordinary
preview is its demo and the patch is not applied again.

One browser job checks the built preview's themes, evidence, slide geometry,
deck review and demo What changed. Fork and Dependabot PRs cannot publish; their
browser checks use the same build's artifact with read-only permissions. Main
and ordinary on-demand rebuilds also validate arm independently, without publishing twice.
Example workspace separately checks a cold scaffold and the local checkout path
for a deck edit on x86; main and releases add arm. Its full edit comparison runs
on main and releases, and on a PR only when What changed code, scaffold assets,
the example, or the comparison test itself changes. Workspace/Overleaf unit
tests use four pytest workers per Python version; other plugins keep their
existing test command and execution model.
