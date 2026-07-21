---
name: workspace
description: Show the user the agent's work on a research project and save iterations on the user's behalf. Scaffold rendering and deploy infrastructure (Quarto today, GitHub Pages, dev container), show the rendered output, save iterations. Doesn't handle research execution (use `asta-flows`).
allowed-tools: Bash(which quarto) Bash(make *) Bash(quarto render *) Bash(quarto preview *) Bash(git *) Bash(gh *) Read(assets/**) Write Edit
---

# Workspace

Manage the writing/docs side of a research project: scaffold infrastructure as needed, show the rendered work, save iterations. For managing the research task graph itself (planning, executing typed tasks), use `asta-flows`.

`assets/DEVELOPER.md` is a developer-facing template scaffolded into the user's project root (where it becomes `DEVELOPER.md` for humans and agents working with the project). This SKILL.md is the agent-specific procedure.

## Show the user the rendered work

Give the user a web URL for the rendered work. Two URL sources, pick based on your context:

- **Local agent** (host, local dev container, or Codespace — the user can reach your port): run `make preview` in the background. Pass the URL Quarto prints (localhost on host/dev container; Codespaces-forwarded URL in a Codespace).
- **Headless agent** (no user-reachable port): push the branch (see **Save**), then `make deployed-url` to fetch the deployed URL from GitHub Pages CI.

## Save

`git add` + `git commit -m "<concise message>"`. **Don't `git push` without explicit user approval.**

For a headless agent (the user only sees results via deployed URL):

- **Bootstrap `main` if the repo is empty.** On a repo with no commits, the first branch pushed becomes the default — leaving no `main` to open a PR against. Check with `git ls-remote --heads origin main`. If absent: prefer having the repo created with an initial commit (GitHub's **"Add a README file"**, or `gh repo create <owner>/<name> --add-readme`) so `main` exists up front; otherwise seed it with `git push -u origin HEAD:main` (legitimate — no prior state to review).
- First save: `git push -u origin HEAD:<feature-branch>`, `gh pr create --fill`, then `make deployed-url` and report the URL.
- Subsequent saves: `git push`, `make deployed-url`.
- After explicit merge approval: `gh pr merge`, `make deployed-url`.

Don't merge a PR without explicit user approval.

## Scaffold components as needed

Add components only when needed; don't proactively offer.

| Component | When to add |
|---|---|
| **Quarto build tool** | Always — it's the project structure. |
| **GitHub Pages deploy** | When you have no user-reachable port, or the user asks for a deployed URL. |
| **Dev container** | User wants to avoid installing host dependencies, or wants browser-only access from another machine. See subsection for the two flows. |

Before writing any file in the steps below, check whether the target path already exists. If it does, ask the user before overwriting, or merge the asset's contents into the existing file.

### Quarto build tool

1. Copy `assets/_quarto.yml` to project root; fill `{{TITLE}}` and `{{REPO_URL}}`. `{{REPO_URL}}` is the source repo's web URL (e.g. `https://github.com/allenai/<repo>`), used for the sidebar GitHub icon that opens the repo in a new tab. Get it from `gh repo view --json url -q .url` or `git remote get-url origin` (normalize any SSH/`git@` form to `https://github.com/...`). If the repo has no remote yet, delete the `sidebar.tools:` block rather than leave the placeholder unfilled, and re-add it once a remote exists.
2. Create `index.qmd` with `title:` frontmatter.
3. Create empty `references.bib`.
4. Append any lines from `assets/gitignore` missing from the project's `.gitignore` (create it if absent; don't overwrite existing entries).
5. Copy `assets/Makefile` to project root, and `assets/quarto-check.sh` to `scripts/quarto-check.sh` (vendored verbatim — the Makefile's `check` target runs it; to update it later, re-copy rather than hand-edit). CI warns when the vendored copy drifts from the canonical one; on that warning, re-copy the asset.
6. Copy `assets/README.md`; fill `{{TITLE}}` and `{{DESCRIPTION}}` from the user.
7. Copy `assets/DEVELOPER.md` to project root. User owns it — only update later with explicit user permission.

### GitHub Pages deploy

1. Copy `assets/docs.yml` to `.github/workflows/docs.yml`. It's a thin stub — the build/deploy/preview machinery lives in this repo's reusable workflow (`.github/workflows/workspace-quarto-site.yml`), so scaffolded projects pick up fixes without re-copying. Project-specific quality gates go in the project's `make check` target, which the reusable workflow calls. When updating an existing project to this stub, update its `Makefile` in the same change (the workflow requires a `check` target), and update any branch-protection required-check names to the new contexts (the build check is now reported as `docs / build`) — via `gh api` if the token has admin on the repo, otherwise ask the user.
2. Configure Pages to serve from `gh-pages`:
   ```bash
   gh api repos/{owner}/{repo}/pages -X POST --input - <<'EOF'
   {"build_type":"legacy","source":{"branch":"gh-pages","path":"/"}}
   EOF
   ```

### Dev container

Copy `assets/devcontainer.json` to `.devcontainer/devcontainer.json`, then pick the flow that matches the user's intent:

- **Local container** (working on their machine without installs): run `make dev` to open VS Code attached to the local container.
- **Codespaces** (browser-based access from anywhere): commit, push to a GitHub remote (creating one if needed), then `gh codespace create` and give the user the URL.
