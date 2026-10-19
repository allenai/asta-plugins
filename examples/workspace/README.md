# Asta workspace example

A small example workspace for the [Asta workspace skill](../../plugins/asta-tools/skills/workspace): a Quarto literature review that cites the workspace [`references.bib`](references.bib), and a separate LaTeX paper paired with an Overleaf project that anyone can [view by link](https://www.overleaf.com/project/6ad3a5f38f722e2e09c9a8f9/share#a44d86bf6428da0098e082455586b759b61d54f5764c735f). Each final asta-plugins release builds it inside that release's `-tex` image and publishes it, with a fixed edit (`scripts/demo-edits.patch`) rendered as a What changed report. Start at the [site home](index.qmd) or the [edited-paper demo](demo/index.qmd). Local preview, VS Code and pull request previews are covered in the skill's [`DEVELOPER.md`](../../plugins/asta-tools/skills/workspace/assets/DEVELOPER.md). Its content is public sample text and public references only.

| File | Role | Rendered on the site? |
|------|------|-----------------------|
| `index.qmd` | Short site home that points to both writing paths. | Yes |
| `demo/index.qmd` | Entry page for the saved What changed example. The rendered snapshot is no longer committed; CI rebuilds it from `scripts/demo-edits.patch`. | Yes |
| `lit-review/index.qmd` | Editable Quarto source for the literature review. | Yes |
| `_quarto.yml` | Quarto project config: which files render, bibliography, theme. | — |
| `references.bib` | Workspace bibliography for the Quarto pages. | — |
| `evidence.yml` | Verbatim quotes behind the `.ev` claim highlights. | — |
| `paper/main.tex` | A separate, hand-edited LaTeX paper, paired with the Overleaf project. | PDF in the PR preview |
| `paper/references.bib` | The paper's own bibliography, which Overleaf co-authors can edit. Entries are copied from `references.bib` when the paper cites them. | — |
| `.asta/overleaf/examples/workspace/paper.json`, at the repository root | The pairing: the Overleaf project's Git URL and the last Overleaf commit synced. It sits outside `paper/` so that it never ships with the paper's source. | No |
| `project.md` | The project plan the [`asta-assistant`](https://github.com/allenai/asta-plugins/tree/main/plugins/asta-assistant) skills read and update: Goal, Background, Completed Work, and Pending Work. `brainstorm` creates it ([format](https://github.com/allenai/asta-plugins/blob/main/plugins/asta-assistant/skills/brainstorm/SKILL.md#outputs)). | No |
| `README.md` | This page. | No |

## Getting a LaTeX PDF

The Quarto review can be rendered to PDF or `.tex` on demand with `quarto render`. The committed `paper/main.tex` gets a PDF, an HTML view and diffs in the preview, built from `paper/` alone, the way Overleaf builds it.

## The Overleaf pairing

The paper is paired with an Overleaf project through [Overleaf sync](../../plugins/asta-tools/skills/workspace/workflows/overleaf-sync.md). A scheduled sync, run outside this repository, publishes the paper to Overleaf after each merged change to `paper/`, so the view-only link matches `main`. An edit made in Overleaf comes back as a sync pull request. Only the project's collaborators can edit it; the public link is view-only.

## Release deployment setup

A repository administrator must enable **Settings → Pages → Source: GitHub Actions**. In **Settings → Environments → github-pages**, select **Selected branches and tags**, then add a **Tag** rule for `v*`. Keep any required approvals; a branch-only rule does not authorize release-tag deployments. See GitHub's [deployment branch and tag rules](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments#deployment-branches-and-tags).

This example owns the repository's Pages site root. Pages was disabled when this workflow was added, and there was no existing site publisher. The reusable `workspace-quarto-site.yml` serves caller repositories, not this repository. Before enabling another publisher here, combine its content with this site instead of replacing the root independently.

Only the newest final `vX.Y.Z` tag can deploy. Deployment jobs share the `pages` concurrency group and recheck remote tags after acquiring the lock, so a late older build cannot replace a newer demo. The [deployment queue](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#example-queueing-multiple-pending-runs) retains pending jobs instead of letting an older build cancel a queued newer one. Prerelease tags are excluded. A failed build never attempts deployment and preserves any existing site; a failed deployment requires checking the live site before retrying. Each release tag reuses one failure issue.

Local demo tests need Python 3.11 or newer, matching the Asta package requirement and published TeX image.
