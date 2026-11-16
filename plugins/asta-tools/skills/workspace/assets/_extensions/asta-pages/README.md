# asta-pages — widgets for a workspace's workflow pages

Shortcodes that turn a run's files into page panels, the way the Asta app shows Theorizer's
results, and that link every panel to the files on disk it was built from:

```markdown
{{< asta-theories data="data/theorizer.json" >}}    <!-- the Theorizer panel -->
{{< asta-theories data="data/theorizer.json,data/theorizer-v2.json" >}}  <!-- several projects -->
{{< asta-literature data="data/papers.json" >}}     <!-- the paper list -->
{{< asta-autods data="autods" >}}                   <!-- AutoDiscovery runs -->
{{< asta-workflow >}}                               <!-- workflow.mmd beside the page, if any -->
{{< asta-files dir=".asta/flows/0004-x/04-gap-map" >}}          <!-- a folder's files -->
{{< asta-doc file=".asta/flows/0004-x/04-gap-map/gaps.md" >}}   <!-- a markdown file, inline -->
```

## Conventions

All a page's author writes is its `title:`. The rest is folders, and data a workflow step
writes:

- **Folders.** A run's files: `.asta/flows/<NNNN>-<workflow>/<NN>-<step>/` (with the run's
  `workflow.yaml` and `README.md`). Its page: `pages/<NNNN>-<workflow>.qmd`, the same NNNN, so
  the two pair up and the pages sort in run order. `_quarto.yml` renders `index.qmd` and
  `pages/*.qmd`, and its sidebar lists the front page, then the pages flat by file name
  (`- auto: "pages/*.qmd"`).
- **Data files.** The widgets' own data (Theorizer site data, AutoDS runs, inline
  documents).
- **Front matter.** `title:` and Quarto's own keys.

**A workflow page is widgets only.** A workspace keeps one page per workflow run,
`pages/<NNNN>-<workflow>.qmd`: its title, a heading per step, and under each heading the widgets
for that step's files, nothing else (no prose, no hand-written tables). The run's files sit in
`.asta/flows/<NNNN>-<workflow>/<NN>-<step>/`, and every widget links them, so a reader follows a
number to the file it came from:

```markdown
---
title: "Gap-driven theory testing"
---

## Gap map

{{< asta-doc file=".asta/flows/0004-gap-driven-theory-testing/04-gap-map/gaps.md" >}}

## Theories

{{< asta-theories data="../.asta/flows/0004-gap-driven-theory-testing/05-theories/theorizer.json" >}}

{{< asta-files dir=".asta/flows/0004-gap-driven-theory-testing/05-theories" >}}
```

- **Theory page:** the theories with their supporting and conflicting counts; the selected
  theory's statements (evidence, conflicting evidence, what it does not account for, novelty),
  predictions, the extracted findings behind it, and its referenced papers. Theories are grouped
  by the query they were generated for (the same text, ignoring spacing, is one query): with one
  query, the query is shown above the table; with several, each gets a tab ("Query 1 · 16
  theories", with the start of what sets it apart from the others) showing its query above its
  own table. Arrow keys, Home and End move between the tabs; the selected tab is kept in the
  URL (`#query-2`). `names="Original|Revised"` labels the tabs instead, in the order the queries
  first appear. `data` may name several files, one per Theorizer project
  (`data="data/theorizer.json,data/theorizer-v2.json"`); a theory in more than one of them
  (same id and name) is shown once, and when two files use the same id for different theories,
  the later file's are anchored as `#theorizer-v2/theory-1`. A file that cannot be read gets
  an error box above the panel, which still shows the others. Only the findings a theory cites
  are embedded (the Evidence tab shows no others), and only the papers a theory or one of those
  findings names, so a run whose file is mostly findings stays small enough for two or more runs
  on one page (nine Theorizer projects of one run and its paper list come to about 10 MB). Choosing a theory or a tab is a
  step in the browser's history, so Back returns to the list or the tab before (also inside the
  app's site frame, whose front door bridge turns the step into an entry of the app's history).
  A paper's title links to its entry on the site's paper list, `papers="papers.html"` (default
  `literature.html`), anchored `#paper-<corpus id or key>`; the list clears its filters if they
  hide the entry, scrolls to it and marks it with the accent halo. A copy of a work the list
  shows once links to the card that lists it.
- **Paper list:** the run's papers, each marked as used by the theories, read in full but not
  used, or not read (abstract only), with a text filter and facets (sort, part in the run, year,
  venue, author). Copies of one work (a preprint and its published version) are shown once.
- **AutoDiscovery runs:** a run as autodiscovery.allen.ai's run page shows it, in these pages'
  style and the site's light and dark colours: the run's header (status, when it finished, how
  many experiments and how many surprising; Open in AutoDiscovery, the CSV, and Session
  configuration with the run's prompt, data and settings), its search tree (circles numbered as
  the table, orange for a surprising result; click to open, drag, zoom), the experiments table
  (sortable, filterable), and the selected experiment: its hypothesis, then Result (belief
  shift, analysis, figures that open full size, review), Plan and Code tabs. `data` names a
  run's `asta autodiscovery results` JSON, the hosted Download → JSON or → CSV, a local run's
  output folder, or a run folder (`run.md` with `experiments.csv` and/or `results.json`: the
  record's title, label, link and `## Prompt` are used, and the CSV's own columns, such as an
  agent review, join the results). The CSV download keeps no tree, code, figures or settings.
  One run per page keeps a page to a few MB (each figure is embedded once, in its smallest
  form); a folder of runs lists them first. Anchors: `#experiment-7` (`#run-2/experiment-7`
  with several runs), and a local run's node id, `#node-3-1` or `#node_3_1` (the node of
  `mcts_node_3_1.json`; `#run-2/node-3-1`).
- **Workflow:** the Mermaid diagram in `workflow.mmd` (or `file="..."`) under a "Workflow"
  heading, drawn by the Mermaid runtime that Quarto ships, copied into the site. With no file it
  renders nothing, so a page can carry it before a diagram exists.

- **Files** (`asta-files dir=...`): a compact list of a folder's subfolders, then its files,
  each with its size and a link, read at render time. `depth=2` lists the subfolders' contents
  too. `__pycache__`, `.DS_Store`, `.git` and names that look like credentials (`.env`, `*.pem`,
  `*.key`, names with `secret`, `token`, `password`, `api_key` ...) are left out. Past 30 entries
  (`limit=`) the list stops with a count and a link to the folder.
- **Document** (`asta-doc file=...`): a step's own markdown output (a gap map, a data
  inventory; not a log) rendered inline, its headings moved under the page's (its top heading
  becomes `level=`, 3 by default, below the page's step heading) and left out of the page's
  table of contents, under a header line linking the file and its folder. Links and images in
  the document that name files beside it point at those files.

**Files.** Every panel carries a small "Files" line linking what it was built from: the data
files (several files in one folder, or several files of one name, are their folder), an
AutoDiscovery run's folder. An AutoDiscovery run's header also
links its folder and `args.json`, and an experiment from a local run its `mcts_node_*.json` and
the run's `rich_outputs/`. A paper list links each search's own file (`<name>.json`) when it is
in a `searches/` folder beside the papers file or beside its folder, or in `searches=` (from the
project root).

**Paths and links.** `data` is relative to the page, as before. The paths the file widgets name
(`dir`, `file`, `searches`) are relative to the **project root**;
an absolute path, or a `..` that leaves the project, is refused with an error box and a render
warning. Hidden folders (`.asta`) work. Links are plain relative URLs from the *rendered* page to
the file in the project, computed from the page's place in the project and the project's
output directory: from `_site/pages/0004-x.html`, `.asta/flows/0004-x/07-tests/T1/design.md` is
`../../.asta/flows/0004-x/07-tests/T1/design.md`, and a folder's link ends with `/`. They are
written as raw HTML (or inside the panels' JSON), which Quarto neither copies into `_site/` nor
warns about. (A link written relative to the *source* page, in Markdown or HTML, makes Quarto
copy the file into the site, hidden folders included, and a `resources: ["!.asta/**"]`
exclusion does not stop it; so do not hand-write such links on these pages.) The links work
where the site is served together with the project's files, as the app's site tab does; a
site published on its own (GitHub Pages) does not carry `.asta/`.

**Figures are served from the site.** A host may serve the output directory and nothing else
(the app's front door serves `_site/` only), so an image a panel shows cannot point at the
workspace's file. Each figure a page shows (an image in an `asta-doc` document) is copied when the page renders to `_site/_asta/files/<its path in the project>`,
with a leading dot in a folder's name made `_` (`.asta/flows/…` → `_site/_asta/files/_asta/flows/…`),
and the `<img>` shows the copy, while the figure's link still opens the workspace's file (as
the app's Files tab does). Only figures the pages show are copied, each up to 2 MB; a larger
figure is not copied, and the page shows a link to the file with its size ("5.1 MB, too large
to show here"). Nothing is downscaled (a render has no image tools it can count on). A page
rendered on its own, outside a project, shows the files themselves.

`data` is relative to the page. The file is read at render time and embedded in the page, so the
page makes no request at view time (a 50-experiment run with its figures is about 4 MB). A
missing or unreadable file renders a visible error box and a render warning. Anchors: `#theory-2` selects a theory, `#finding-<uuid>` opens the Evidence tab
at that row, `#query-2` selects a query's tab, `#paper-<corpus id>` scrolls to a paper.

The data files are written by the run-workflow skill's theory-generation workflow
(`workflows/theory-generation/scripts/theorizer-site-data`), from a `theorize` project; each
theory carries its `query`. A second project's file (`data/theorizer-v2.json`) gets its own
papers file beside it (`data/papers-v2.json`), leaving the first one's `papers.json` as it is. Plain
HTML, CSS and JavaScript; the panels follow the asta-theme light (cream) and dark modes. The
files the panels link are loaded when the reader opens them.

`make workspace-assets` fetches this extension when a page uses one of its shortcodes, like the
evidence extension. To customize it, commit a copy of `_extensions/asta-pages` and remove its
line from `.gitignore`.
