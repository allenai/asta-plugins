# Asta workspace example

A small example workspace for the [Asta workspace skill](../../plugins/asta-tools/skills/workspace): a Quarto literature review that cites the workspace [`references.bib`](references.bib), and a separate LaTeX paper paired with an Overleaf project that anyone can [view by link](https://www.overleaf.com/project/6ad3a5f38f722e2e09c9a8f9/share#a44d86bf6428da0098e082455586b759b61d54f5764c735f). Main publishes it through the same shared workflow as any workspace, and each pull request that changes it gets a preview. See it live: [the example's site](https://allenai.github.io/asta-plugins/), as a project's readers see it, and [the demo](https://allenai.github.io/asta-plugins/demo/), the sample edit in [`examples/workspace-demo.patch`](../workspace-demo.patch) built on every push to main as a pull request's reviewers see it, whose [What changed](https://allenai.github.io/asta-plugins/demo/what-changed.html) lists that edit's changes to the paper, a slide, and the literature review, which the edit changes in each kind of content a workspace holds (prose, a heading, a list, a table, equations, a regenerated figure, a figure replaced by a file with a new name, a Mermaid diagram, a Graphviz diagram, code, a callout, a link, a source comment), except content computed when the page renders, since the example renders without Jupyter. Local preview, VS Code and pull request previews are covered in the skill's [`DEVELOPER.md`](../../plugins/asta-tools/skills/workspace/assets/DEVELOPER.md). Its content is public sample text and public references only.

| File | Role | Rendered on the site? |
|------|------|-----------------------|
| `index.qmd` | Short site home that points to both writing paths. | Yes |
| `lit-review/index.qmd` | Editable Quarto source for the literature review. | Yes |
| `lit-review/figures/` | The review's figures: `path-length.svg`, with `sequence-length.txt`, the input it is drawn from, and `seen-512.svg`. | Yes, with the review |
| `scripts/path-length.py` | Redraws the figure from its input, standard library only: `python3 scripts/path-length.py`. | — |
| `slides/attention/slides.qmd` | A three-section reveal.js talk, built with the example. | Yes; viewer page `slides/attention/index.html` in the site, standalone `slides/attention/slides.html` to present |
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

## Site publication

`.github/workflows/example-preview.yml` calls the repository's own
`workspace-quarto-site.yml` with `site-dir: examples/workspace`. Main publishes
only to the `gh-pages` root; PR previews use `pr-preview/pr-<N>/` and compare
with the published main site. Unrelated PRs skip rendering and comments, and
closing a PR always removes its preview. The stable **Example preview browser**
check passes without browser work for unrelated PRs and can be required.

For the initial migration, wait until the first successful main publication has
written the root, then an administrator switches **Settings → Pages → Deploy
from a branch**, branch **gh-pages**, folder **/ (root)**. Until then the existing
Actions deployment stays live. Releases validate the example but never publish.
The new PR-preview and What changed links above become available only after
that switch and a successful preview build; their temporary unavailability does
not mean the existing live site has been removed.

### The demo

The sample edit has one copy, [`examples/workspace-demo.patch`](../workspace-demo.patch). Every push to main rebuilds the demo from it; there is no demo branch or pull request to maintain. A patch that no longer applies fails main's site build with the patch path in the error.
