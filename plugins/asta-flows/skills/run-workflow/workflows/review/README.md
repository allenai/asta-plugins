# Computational review

Write the project's report as a critical review of the evidence, with the Expert Review Pipeline of [ComputationalReviewTemplate](https://github.com/AllenNeuralDynamics/ComputationalReviewTemplate/tree/8cc838383453d192211413e3ff96dc1ebf3e227a#readme) (Allen Institute for Neural Dynamics, MIT). Nothing of it is copied here: read it from the repository, at this commit.

The template's sections are the default. If the person has a template of their own, or has refined the report's sections, keep theirs, and run the pipeline's phases inside them.

- [README](https://github.com/AllenNeuralDynamics/ComputationalReviewTemplate/tree/8cc838383453d192211413e3ff96dc1ebf3e227a#readme): the phases, and why writers and critics are kept apart.
- [`skills/`](https://github.com/AllenNeuralDynamics/ComputationalReviewTemplate/tree/8cc838383453d192211413e3ff96dc1ebf3e227a/skills): the pipeline. Start at `comprev-orchestrator.md`; `manifest.json` lists the rest.

```bash
REF=8cc838383453d192211413e3ff96dc1ebf3e227a
RAW=https://raw.githubusercontent.com/AllenNeuralDynamics/ComputationalReviewTemplate/$REF
mkdir -p <run>/comprev
for f in $(curl -fsSL "$RAW/skills/manifest.json" | jq -r '.skills[].file'); do
  curl -fsSL "$RAW/$f" -o "<run>/comprev/$(basename "$f")"
done
```

Follow its phases, gates and information barriers as written. Where a skill calls the Claude Science host (`host.delegate`, `host.artifacts`), use your own subagents and hand them the skill files by path. Where your harness cannot start subagents, run each writer and critic as its own headless agent process (for example Claude Code's `claude -p`), started in a folder that holds only the files that role may see, so a blinded critic cannot read what it should not.

## Plan

| Step | What it does | Pipeline phases |
|---|---|---|
| 1 | Scopes the review and gathers the evidence | 1 to 6 |
| 2 | Drafts the sections, with blinded critics | 7 to 13 |
| 3 | Assembles the review and checks every citation against its source, then fixes | 14 to 19 |
| 4 | Renders it on the site | 20 and 21, as below |

## Two changes

**1. The `workspace` skill (asta-tools) forms the citations, the bibliography, the evidence and the site,** in place of the template's MyST, CrossRef and GitHub Pages steps:

| The template | Here |
|---|---|
| `content/*.md`, `myst build` | the workspace's pages (`index.qmd` is the report), `quarto render` or `make check` |
| citation key map and `references.bib` from CrossRef | the site's `references.bib`, a paper keyed `s2-<corpus id>` |
| a claim's supporting passage | an `evidence.yml` entry with the verbatim quote, and an `.ev` span on the claim |
| citation verification | the `check-claims` skill |
| push and deploy to GitHub Pages | the workspace's **Save** and **Show the user the rendered work** |

Everything else in the pipeline still runs, including figure construction and the figure audit. The figures go in the review page as Quarto figures: copy each image into the site, and keep its script and inputs beside it in the run's folder. Each figure's folder carries a `figure.json` naming its script, inputs and audit (`{"id": "<fig-id>", "script": "make_figure.py", "inputs": ["<workspace path>", …], "audit": "audit.json"}`), so the site links the figure to the files it was made from.

**Never skip the figure audit.** Phase 6 checks the figures built from other studies' numbers. Audit the project's own figures the same way: a blinded critic gets each figure, its caption and the files its `figure.json` names, and checks that the figure shows what the caption says and was made from those files. Redraw or fix every figure it flags before the review is shared.

The review is the site's `index.qmd`, and the only page this workflow writes: it gets no `pages/<NNNN>-review.qmd`. In `_quarto.yml` the front page's sidebar entry reads "Computational review". The run's final files are listed at the end of the review under a short "Files" heading (`{{< asta-files dir=".asta/flows/<NNNN>-review/<final step>" >}}`).

**2. A local document without a DOI is fine.** Cite it with a stable local key, and give its entry the same fields as a paper with a corpus id, so the two render alike:

```bibtex
@article{s2-267095315,
  title = {{The paper's title}},
  author = {Liu, Ziming and Tegmark, Max},
  year = {2023},
  journal = {arXiv.org},
  url = {https://www.semanticscholar.org/p/267095315}
}

@article{local-field-notes-2024,
  title = {{The document's own title}},
  author = {Its Author},
  year = {2024},
  journal = {Lab report},
  url = {asta://...}
}
```

The `url` is the document's `asta://` URI when it is indexed with the `asta-documents` skill. Without one, leave `url` out: the site does not serve a path in the project. Its evidence quotes cite `local-<name>` the way a paper's cite `s2-<corpus id>`.
