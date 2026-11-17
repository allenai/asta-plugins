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

### CI tool updates

CI installs Claude Code, Codex, and `plugins` from the
[npm lockfile](ci-tools/package-lock.json) and records the installed
versions in the run summary. Dependabot checks for releases every day, including
weekends, and opens a separate PR for each update. The schedule skips the
release-age delay to test new releases within about a day. CI runs those PRs with
read-only repository permissions in the jobs that execute the CLI tools.

Auto-merge relies on the `main` ruleset requiring `tests-ok`, which covers the
Python tests and both model-visible skill checks. Major releases follow the same
auto-merge path as other releases. An update that fails CI stays open, unmerged.

The lockfile lives in `ci-tools/`, not `.github/`: GitHub rejects Dependabot npm
PRs that change files under `.github/` (dependabot/dependabot-core#15237), and that
failure stays in Dependabot's own run without opening a PR. So stalls are caught by
outcome, not by watching each step: a daily freshness check
(`ci-tools-freshness.yml`, 4 hours after Dependabot's check) looks for a stable
release that was available by Dependabot's last check but is newer than the version
`main` locks. If Dependabot starts late or CI and auto-merge take more than four
hours, an issue can open while the update is still in flight. The check is the
only workflow that manages the `CLI update stuck: <cli>` issue. It opens an
issue, updates the body of the Actions-created alert while the update is overdue,
and closes it once `main` has caught up. Each run recomputes which updates are
overdue from npm and the lockfile. This catches updates stalled before PR
creation, in CI, or at merge. If npm cannot provide release data with a stable
`latest` tag, the check leaves that package's issue untouched, checks the
remaining packages, and reports a failed run.

GitHub suppresses `push`
workflows for merges performed with Actions' built-in token. The required checks
run before the merge. Release tags still use the release commit with its own
successful main-push Docker build.

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

`make set-version` keeps them in sync; CI on every PR enforces it.

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
5. Merge it. Merging the version bump is the release: `release.yml` sees that
   `main`'s version has no `v<version>` tag, runs `workspace-release-checks.yml`
   on both architectures, and waits for the `Docker` workflow run on that commit
   to succeed (`scripts/wait-for-main-image.sh`). When both pass it pushes the
   tag with its own `GITHUB_TOKEN` and dispatches `docker.yml` at the tag, since
   a `GITHUB_TOKEN` tag push starts no workflows. If either pre-tag check fails,
   Release pushes no tag and comments on the merged PR. After tagging, Release
   waits for Docker promotion and reports dispatch or Docker failures on the
   PR. Re-run the failed Release jobs to retry. A later push to `main` also
   retries the same version, using the recorded tag commit if it was tagged.
   Until the tag exists, the plugin's `SessionStart` hook keeps the installed
   CLI or installs the `latest` release. Every PR runs
   `manage-version.py check`, so a partial bump fails before it merges.
   Every `main` push publishes run-specific candidates
   (`ghcr.io/allenai/asta:sha-<commit>-run-<id>-attempt-<n>` and `…-tex`) and
   smoke-tests them by digest; candidates never move `:latest`. The tag does not
   rebuild: `docker.yml` promotes the validated candidate digests to `:<tag>` /
   `:<tag>-tex`, and a final `vX.Y.Z` tag (not `-rc.N`) then moves `:latest` /
   `:latest-tex` to the highest final release. `make push-version-tag` remains
   the manual fallback (it needs a successful `workspace-release-checks.yml`
   dispatch on the commit); a tag pushed by a person starts `docker.yml` itself.
6. *(Future)* Publish to PyPI: `make publish` (or `make publish-test` for
   TestPyPI).
7. *(Future)* Create a GitHub release from the tag for human-readable notes.
   This is bookkeeping only — the Docker image is already published by step 5, so
   a release is not a prerequisite for anything.
8. Check [the demo](https://allenai.github.io/asta-plugins/demo/what-changed.html). Main rebuilds it from `examples/workspace-demo.patch` on every push; no release step maintains a demo branch.

Workspace browser coverage runs on workspace PRs and release/manual validation.
Main only publishes the site and patch-derived demo. Pre-release checks use the
current released `latest-tex` toolchain; the new tag does not exist yet. Browser
slide fixtures use the shared site's Quarto setup (`release`).

If CI or `push-version-tag` reports a version mismatch, rerun `make set-version` to
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
normal Pages artifact; it adds no publishing workflow or credential. A workspace PR builds the site and demo once, on x86, through the
shared site workflow. The patch is applied only by that build's artifact hook.
One browser job checks that build's preview (or its identical artifact for fork
and Dependabot PRs) with read-only permissions. The artifact hook validates the existing paper output without rebuilding it.
Separate GitHub jobs check cold asset bootstrap and the local deck-edit path and all 13 selected/full comparison cases. Neither waits
on the published site.
Cold bootstrap checks the managed assets, generated viewers and check gate without
rendering another site. The shared build runs the example's full `make check` and
validates its rendered paper. Arm browser validation downloads that build's
artifact into a separate job, so a browser failure is distinct from a build failure.

### Workspace checks

The Makefile owns workspace check selection. `WORKSPACE_PATHS` defines one
conservative workspace-change trigger, shared by both example workflows.
New offline tests belong in `tests/workspace/`; tests that execute Quarto or TeX
belong in `tests/workspace/tools/`. A required missing tool fails its target.

| Target | Checks | Trigger | Environment |
|---|---|---|---|
| `test-plugins` | Other plugins' existing serial tests | Every PR | Python, existing plugin CLI setup |
| `test-workspace` | Offline workspace and Overleaf tests | Workspace PR | Python, Make and Perl; Python 3.11–3.13, eight GitHub shards |
| `check-workspace-tools` | Real scaffold/slide/template tests, cold scaffold checks and local deck comparison | Workspace PR | Released TeX image, Quarto and Chromium |
| `workspace-compare` | Selected vs full What changed, one `WORKSPACE_CASE` | Workspace PR | Released TeX image; 13 independent GitHub jobs |
| `workspace-dom` | What changed folding | Workspace PR | Node |
| `workspace-browser` | Themes, evidence, slides, deck review and published demo | Workspace PR, after its single site build | Quarto, Node, Python and Chromium |
| `workspace-demo` | Build the patch's demo and What changed | Site build; main publication | Released TeX image |
| `workspace-status` | Aggregate results, allowing only intended skips | Every PR; release/manual | Python and GitHub job metadata |

Local targets run the same commands as CI. `make test-workspace` defaults to the
whole offline suite; `WORKSPACE_SHARD` and `WORKSPACE_SHARDS` select CI's partition.
`make workspace-compare` runs all 13 cases; `WORKSPACE_CASE=quote` selects one.
`make workspace-cases` supplies CI's job matrix from that same case list, so a new
case needs no YAML edit.
`make workspace-browser PR_NUMBER=296` checks the downloaded preview directory.
For a local artifact, pass `PREVIEW_SITE=/path/to/site`; `PR_NUMBER` defaults to
`0`, disabling only the PR URL check.

`workspace-ok` is the stable aggregate result for the offline and DOM jobs, the
workspace tests that run no render or browser. It fails on failed, cancelled or
unexpectedly skipped jobs, and passes when an unrelated PR deliberately skips them
all. The tools and comparison jobs render and drive a browser, so they can flake:
they show on each workspace PR without blocking it, and the release checks below
run them. A maintainer should require `workspace-ok` in the repository's merge
rules, rather than individual matrix names. Workflow changes do not configure
those repository settings.

The Release workflow runs `workspace-release-checks.yml` for an untagged
version on `main`. It reuses the plugin and dev-container checks and runs
workspace tests, comparisons, browser checks and site builds on x86 and arm
without publishing. For a manual release, dispatch it at the exact commit and
wait for it to pass before running `make push-version-tag`. Regular pushes to
`main` publish the example and its patch-derived demo.
