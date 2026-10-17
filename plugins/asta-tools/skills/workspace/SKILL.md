---
name: workspace
description: Show the user the agent's work on a research project and save iterations on the user's behalf. Scaffold rendering and deploy infrastructure (Quarto today, GitHub Pages, dev container), show the rendered output, save iterations. Doesn't handle research execution (use `asta-flows`).
allowed-tools: Bash(which quarto) Bash(make *) Bash(quarto render *) Bash(quarto preview *) Bash(asta workspace sync) Bash(asta workspace sync *) Bash(asta workspace bump-pin) Bash(asta workspace bump-pin *) Bash(asta workspace preview) Bash(asta workspace preview *) Bash(asta workspace what-changed *) Bash(git *) Bash(gh *) Read(assets/**) Write Edit Skill(asta-tools:check-claims)
---

# Workspace

Manage the writing/docs side of a research project: scaffold infrastructure as needed, show the rendered work, save iterations. For managing the research task graph itself (planning, executing typed tasks), use `asta-flows`.

`assets/DEVELOPER.md` is the shared developer guide. Link to it from the project README at the selected asta-plugins ref; do not copy generic instructions into every project. This SKILL.md is the agent-specific procedure.

## Show the user the rendered work

Give the user a web URL for the rendered work. Two URL sources, pick based on your context:

- **Local agent** (host, local dev container, or Codespace — the user can reach your port): run `make preview` in the background. Pass the URL Quarto prints (localhost on host/dev container; Codespaces-forwarded URL in a Codespace).
- **Headless agent** (no user-reachable port): push the branch (see **Save**), then `make deployed-url` to fetch the deployed URL from GitHub Pages CI.

When the user wants to see what changed since an earlier version, offer `asta workspace what-changed <ref>` (Git 2.30 or newer). It runs the project's `make render` at the named ref and in a private working-tree copy, then reuses the PR preview's diff script. It publishes only to `.asta/cache/what-changed/`; live preview can stay open. Run `asta workspace preview --what-changed` in the background and give the user its port-4849 URL (localhost or Codespaces-forwarded). A running server picks up later comparisons. No PR or Pages deploy is needed. Tracking the last-read version stays with the user; suggest `git tag -f last-read` after they read.

Choose a trusted ref and keep source files stable while the copy is made. The baseline contains only committed files; do not present current ignored inputs as historical data. Run comparisons one at a time. See [the developer guide](assets/DEVELOPER.md#auto-deploy-githubworkflowsdocsyml) for build prerequisites, copying costs, cleanup and serving limits.

## Before landing paper changes

Before merging a paper PR or pushing paper edits directly to the default branch
where allowed, check for an open PR labeled `asta:overleaf-sync`. Let it merge
first so newer co-author edits conflict on your change before it lands. If it
has not caught up, run `asta workspace overleaf sync` where the Overleaf token
is available, then update your branch. Resolve a sync conflict on that PR and
rerun its checks; do not bypass it by advancing `overleaf.json` manually.
For scheduling, invited-coauthor access, lock recovery and repository status,
read [Overleaf sync](workflows/overleaf-sync-command.md).

## Save

`git add` + `git commit -m "<concise message>"`. **Don't `git push` without explicit user approval.**

Before opening any workspace PR, for both local and headless agents:

- **Keep the pin current.** Before opening a PR, run `make check` and record its exit status as the pre-bump baseline. When `.github/workflows/docs.yml` pins a release older than this asta's final release, `asta workspace bump-pin` commits the move as its own commit; `main`, `latest`, commits and newer pins are left alone.
- **Record the actual bump.** Record `git rev-parse HEAD` immediately before running `asta workspace bump-pin` and again immediately afterward, in a separate step that runs even if the command fails or is interrupted. Do not gate the second read on its exit status or output, and make no other commits between the reads. If HEAD changed, verify that the new HEAD has the saved HEAD as its sole parent (`git rev-list --parents -n 1 HEAD`), has a `Move workspace pin to asta-plugins@...` subject, and changes only the workflow's release ref in `.github/workflows/docs.yml` (`git show --format=fuller HEAD`). Record that verified SHA as the bump commit and check it below even if the command failed before printing success. If either HEAD read fails or the new commit does not match, inspect and resolve the state before opening the PR; never guess which commit to undo. If HEAD is unchanged, there is no bump commit to drop. Preserve the work and report any command failure.
- **Check the bump.** When a bump commit was created, run `make check` again. If the baseline passed and this check fails, undo only the recorded bump as described below, then rerun `make check` to verify recovery and continue the PR without the upgrade. If the baseline already failed, undo the bump the same way and resolve the original build failure independently.
- **Undo only the bump.** Run `git revert --no-commit <bump-commit-sha>`; only after it succeeds, run `git commit --only -m "Revert workspace pin bump <bump-commit-sha>" -- .github/workflows/docs.yml`. This commits only the rollback and preserves unrelated staged work. Never infer a bump from `HEAD`, drop `HEAD~1`, or undo anything when no bump was created. If reverting fails or conflicts, preserve the work and resolve only the bump's workflow edit before committing that path. A PR that shouldn't carry a bump undoes that recorded commit the same way; never let the bump block the work.

For a headless agent (the user only sees results via deployed URL):

- **Bootstrap `main` if the repo is empty.** On a repo with no commits, the first branch pushed becomes the default — leaving no `main` to open a PR against. Check with `git ls-remote --heads origin main`. If absent: prefer having the repo created with an initial commit (GitHub's **"Add a README file"**, or `gh repo create <owner>/<name> --add-readme`) so `main` exists up front; otherwise seed it with `git push -u origin HEAD:main` (legitimate — no prior state to review).
- First save: complete the pin checks above, then `git push -u origin HEAD:<feature-branch>`, `gh pr create --fill`, then `make deployed-url` and report the URL.
- Subsequent saves: `git push`, `make deployed-url`.
- After explicit merge approval: `gh pr merge`, `make deployed-url`.

Don't merge a PR without explicit user approval.

## Overleaf sync refusals

When `asta workspace overleaf pull` or `publish` refuses, or a sync PR conflicts, follow the section its message links in [`workflows/overleaf-recovery.md`](workflows/overleaf-recovery.md).

## Scaffold components as needed

Add components only when needed; don't proactively offer.

| Component | When to add |
|---|---|
| **Quarto build tool** | Always — it's the project structure. |
| **Version workflow stub** | Always for managed rules; enable automatic Pages deploy only when needed. |
| **GitHub Pages deploy** | When you have no user-reachable port, or the user asks for a deployed URL. |
| **Dev container** | User wants to avoid installing host dependencies, or wants browser-only access from another machine. See subsection for the two flows. |

Before writing any file in the steps below, check whether the target path already exists. If it does, ask the user before overwriting, or merge the asset's contents into the existing file.

### Quarto build tool

1. Copy `assets/_quarto.yml` to project root; fill `{{TITLE}}` and `{{REPO_URL}}`
   (use the canonical GitHub URL, e.g. `https://github.com/{owner}/{repo}`).
2. Create `index.qmd` with `title:` frontmatter.
3. Create empty `references.bib`.
4. Copy `assets/evidence.yml` to the project root (the keyed quote store — keep it even while empty). The Makefile fetches the hover-snippet extension from this repository before each render, so do not vendor `assets/_extensions/evidence/` into the project. See **Back claims with supporting evidence** below.
5. Append any lines from `assets/gitignore` missing from the project's `.gitignore` (create it if absent; don't overwrite existing entries).
6. Copy `assets/Makefile.managed` as `Makefile`. Shared rules and scripts are fetched by `asta workspace sync` into ignored `.asta/cache/`; do not create `scripts/` or copy helpers unless the user wants to customize them. A project-owned `workspace.mk` or `scripts/<name>` takes precedence. Preserve existing project targets when adopting the scaffold.
7. Add the thin `assets/docs.yml` workflow stub even for local-only projects: it selects the managed version. For local-only use, remove its `on.push` and `on.pull_request` events and use `on.workflow_dispatch` so publishing requires manual activation. Keep the `jobs.docs.uses` line; sync reads it. Preserve an existing version policy (`@main` canary, `@latest` release channel, or a fixed release/commit). Do not upgrade or repin it as part of unrelated setup.
8. Copy `assets/README.md`; fill `{{TITLE}}`, `{{DESCRIPTION}}` and `{{ASTA_PLUGINS_REF}}`. Use the ref in `.github/workflows/docs.yml` for the guide link. The upstream `latest` branch tracks the released guide; verify the link for a custom ref.
9. Run `asta workspace sync --require-scripts`, then `make check`. Keep customized copies. Before removing old unmodified helpers, require a successful refresh and validate the project from an empty cache.
10. To keep the paper in step with an Overleaf project, follow [`workflows/overleaf-sync.md`](workflows/overleaf-sync.md).

### Separate LaTeX paper (optional)

Add this only when the user wants to write LaTeX directly. Quarto-to-PDF remains an on-demand `quarto render <page>.qmd --to pdf`; do not create or commit its generated `.tex`, PDF, HTML or viewer pages.

1. Copy `assets/paper/main.tex` and `assets/paper/latexmkrc` into `paper/` (or the chosen paper directory), preserving existing paper sources and engine settings. Fill `{{TITLE}}`, escaping LaTeX special characters such as `&`, `%`, `_`, `#`, `$`, braces and backslashes. When built from the paper directory, the rc searches upward for `references.bib`, stopping at the Git root; add citations as references become available and uncomment the starter's bibliography line. An empty project builds without a reference list. Keep the separate paper's writing independent from the Quarto pages. `project.md` belongs to asta-assistant's `brainstorm`, not this scaffold.
2. Append missing entries from `assets/paper/gitignore` to `.gitignore`, replacing `{{PAPER_DIR}}` with the chosen relative directory (`paper` by default). Repeat for each paper, including nested directories; escape any Git ignore pattern characters in directory names. The source and rc are committed; build outputs and generated viewers are ignored. A committed custom viewer still wins after its ignore rule is removed.
3. Use the `-tex` image in the dev container. It supplies TeX, LaTeX Workshop and editor defaults; do not copy `.vscode/settings.json`. Retain the project's chosen version/channel when selecting the image.
4. The shared rules provide `make paper` and `make paper-clean`; `PAPER_DIR=<directory>` selects another paper. Existing projects on older refs can keep their own targets until upgrading to a ref that provides these. Projects can override a target or eject `workspace.mk`.
5. The managed viewer is `<paper-dir>/html/index.qmd`. Add it to `project.render` only when the project has an explicit render allowlist, and link `<paper-dir>/html/index.html` from the site. Keep existing page lists/navbar entries. Shared viewer generation handles the required JavaScript resource; do not commit viewer source.
6. Run `make paper` (with `PAPER_DIR` for a non-default directory) and `make check`. If the selected released rules do not yet provide `paper`, use `(cd paper && latexmk -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build main.tex)` with the chosen directory, or LaTeX Workshop instead; do not silently change the project's ref or add a copied Make recipe. The shared CI paper preview already works on these older refs. With Pages enabled, verify the PR preview's paper PDF, its paper page and What changed. One TeX image supports multiple papers: discovery finds `main.tex` with a neighboring `latexmkrc`, including nested directories.

### Back claims with supporting evidence

The scaffold fetches a small Quarto extension (`_extensions/evidence/`) from `asta-plugins` before each render rather than vendoring a copy that can drift. Managed projects use the ref selected in `.github/workflows/docs.yml`; change that one ref and run `make update-workspace` to upgrade. A standalone, ejected Makefile can set `ASTA_PLUGINS_REF` separately. The extension lets a factual claim in the prose carry the evidence backing it: the claim gets a subtle dotted underline, and hovering (or keyboard-focusing) it reveals a verbatim quote plus a body-style citation. It renders with pure CSS — so it also survives onto the `what-changed` diff page, where a reviewer can check each claim's backing without leaving the diff.

When you write a claim you looked up, back it: add a keyed entry to `evidence.yml` with the **verbatim** quote, its `cite` key (add the paper to `references.bib`), an optional native citeproc `locator` (`p. 4`, `sec. 3.2`, `abstract`, …), and optional `provenance:`. Provenance must record only observed facts: use the exact CLI subcommand (for example, `asta papers snippet-search`) as `method`, use the canonical `asta://` URI returned for an indexed Asta document as `url`, and omit unknown fields rather than inferring a skill or producer name. Then mark the claim in the `.qmd`:

```markdown
NatureBench has [90 tasks]{.ev key="naturebench-count"}.
```

Only ever put a **verbatim** quotation in `quote:` — there is no paraphrase mode; state your own wording in the prose. Full field reference and design notes are in `_extensions/evidence/README.md`.

Structural validation of these entries belongs in deterministic build tooling. Whether a claim needs evidence at all, and whether a quote actually supports the claim as worded, is a judgement call — load the `check-claims` skill for that, both before you open a PR and when reviewing one.

### GitHub Pages deploy

1. Copy `assets/docs.yml` to `.github/workflows/docs.yml`. It's a thin stub — the build/deploy/preview machinery lives in this repo's reusable workflow (`.github/workflows/workspace-quarto-site.yml`), so scaffolded projects pick up fixes without re-copying. Project-specific quality gates go in the project's `make check` target, which the reusable workflow calls. When updating an existing project to this stub, update its `Makefile` in the same change (the workflow requires a `check` target), and update any branch-protection required-check names to the new contexts (the build check is now reported as `docs / build`) — try it with `gh api`; if GitHub refuses, give the user the command.
2. Configure Pages to serve from `gh-pages` with the shipped `assets/github-pages.json`: run `gh api repos/{owner}/{repo}/pages -X POST --input <skill-dir>/assets/github-pages.json`; if GitHub refuses, give the user that command, the file and GitHub's error. Read it back with `gh api repos/{owner}/{repo}/pages` and confirm the source matches; if Pages already exists with another source, tell the user.
3. Optional, for this or any GitHub repo you set up: recommend repo protections (default-branch rulesets, required docs checks). Read `workflows/repo-protections.md` and follow it before proposing or applying any.

On every PR the workflow publishes a full rendered preview under
`<pages>/pr-preview/pr-<N>/` and a `what-changed.html` beside it. The latter
highlights rendered additions and removals against the deployed base site and
collapses unchanged sections. The single preview comment links to the changes
first and the full preview second, so reviewers can inspect the affected
content directly.

### Dev container

Copy `assets/devcontainer.json` to `.devcontainer/devcontainer.json`. If the project has a `paper/`, change `image` to the `-tex` variant (`ghcr.io/allenai/asta:latest-tex`, or `<version>-tex` when pinned) so LaTeX Workshop builds with the same TeX packages as the PR preview. The `-tex` image adds the LaTeX Workshop extension through its dev container metadata, so do not list it in `devcontainer.json`; one image covers any number of papers. Then pick the flow that matches the user's intent:

- **Local container** (working on their machine without installs): run `make dev` to open VS Code attached to the local container.
- **Codespaces** (browser-based access from anywhere): commit, push to a GitHub remote (creating one if needed), then `gh codespace create` and give the user the URL. Authenticate with `asta auth login` in the codespace terminal (persisted across rebuilds) or the optional `ASTA_TOKEN` Codespaces secret. Port 4848 raises a notification (`onAutoForward: notify`) and the forwarded preview URL is printed in the attach terminal. Open either link in a separate browser tab. `localhost:4848` in Simple Browser does not reach a browser-based codespace's forwarded port, and a private forwarded URL may fail in its embedded frame. Local VS Code can use **Ports → Preview in Editor**.
