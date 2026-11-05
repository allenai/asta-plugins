# {{TITLE}}

{{DESCRIPTION}}

Project documents are in [`index.qmd`](index.qmd). Citations: [`references.bib`](references.bib). See the [workspace developer guide](https://github.com/allenai/asta-plugins/blob/{{ASTA_PLUGINS_REF}}/plugins/asta-tools/skills/workspace/assets/DEVELOPER.md) for building, editing and customization.

| File | Purpose |
|------|---------|
| `index.qmd` | The Quarto page rendered on the site. Add other pages to `_quarto.yml`'s `render:` list. |
| `_quarto.yml` | Quarto project settings, including the render list and bibliography. |
| `references.bib` | Bibliography shared by Quarto pages and any separate LaTeX paper. |
| `evidence.yml` | Source quotes behind evidence highlights in Quarto pages. |
| `project.md` (if present) | The project plan the [`asta-assistant`](https://github.com/allenai/asta-plugins/tree/main/plugins/asta-assistant) skills read and update: Goal, Background, Completed Work, and Pending Work linking to `work/<slug>/README.md`. `brainstorm` creates it ([format](https://github.com/allenai/asta-plugins/blob/main/plugins/asta-assistant/skills/brainstorm/SKILL.md#outputs)). It is not a site page. |
| `README.md` | Project introduction and links to shared developer instructions; not a site page. |
