---
name: Preview
description: Render and deploy project documents, reports, and notebooks. Use when docs need to be shared or when previewing how documents render with citations and formatting.
allowed-tools:
  - Bash(quarto render *)
  - Bash(quarto preview *)
  - Bash(which quarto)
  - Bash(gh run list *)
  - Bash(gh run view *)
---

# Preview

Render and deploy project documents, reports, and notebooks using [Quarto](https://quarto.org).

## Usage

If `_quarto.yml` or `.github/workflows/docs.yml` is missing, complete the setup sections below first.

Push the branch. CI renders and deploys automatically. PR preview URLs: `https://<owner>.github.io/<repo>/pr-preview/pr-<number>/` (private repos use an obfuscated domain but the same path structure). Check CI status with `gh run list` / `gh run view`.

For local preview: `quarto preview` (hot reloads). One-time build: `quarto render`.

## Quarto Project Setup

If the project doesn't have a `_quarto.yml` yet, confirm the plan with the user, then:

1. Check `which quarto`. If not installed, see https://quarto.org/docs/get-started/ (may require sudo).
2. Copy [assets/_quarto.yml](assets/_quarto.yml) to the project root and adjust the title.
3. Create an `index.md` with YAML frontmatter (`title:` at minimum).
4. Add `_site/` and `.quarto/` to `.gitignore`.
5. Each subdirectory needs an `index.md` or its sidebar link will 404.

## GitHub Pages Setup

Set this up to deploy rendered docs via GitHub Pages with PR previews. If the project doesn't have `.github/workflows/docs.yml` yet, confirm the plan with the user, then:

1. Copy [assets/docs.yml](assets/docs.yml) to `.github/workflows/docs.yml`. This workflow renders with Quarto, validates the output (fails on warnings like broken citations), and deploys with PR preview support.
2. Pages must serve from the **`gh-pages` branch**, not "GitHub Actions" workflow mode — the artifact model can't host PR previews alongside the main site.
   ```bash
   gh api repos/{owner}/{repo}/pages -X POST --input - <<'EOF'
   {"build_type":"legacy","source":{"branch":"gh-pages","path":"/"}}
   EOF
   ```
3. Require CI to pass and PRs for all changes to `main`. This overwrites existing branch protection ([docs](https://docs.github.com/en/rest/branches/branch-protection)):
   ```bash
   gh api repos/{owner}/{repo}/branches/main/protection -X PUT --input - <<'EOF'
   {
     "required_status_checks": {"strict": false, "contexts": ["build-and-deploy"]},
     "enforce_admins": false,
     "required_pull_request_reviews": {"required_approving_review_count": 0},
     "restrictions": null
   }
   EOF
   ```
