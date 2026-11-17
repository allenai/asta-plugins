# Asta Templates

Enable users to embed Asta's widgets for theories, literature, and discovery in html.

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
{{< asta-tests dir=".asta/flows/0004-x/07-tests" index=".asta/flows/0004-x/06-designs/tests.json" >}}
{{< asta-datasets >}}                               <!-- the datasets in .asta/datasets.json -->
```

## Conventions

All a page's author writes is its `title:`. The rest is folders, and data a workflow step
writes:

- **Folders.** A run's files: `.asta/flows/<NNNN>-<workflow>/<NN>-<step>/` (with the run's
  `workflow.yaml` and `README.md`). Its page: `pages/<NNNN>-<workflow>.qmd`, the same NNNN, so
  the two pair up and the pages sort in run order. `_quarto.yml` renders `index.qmd` and
  `pages/*.qmd`, and its sidebar lists the front page, then the pages flat by file name
  (`- auto: "pages/*.qmd"`).
- **Data files.** The widgets' own data (Theorizer site data, test summaries and indexes,
  AutoDS runs, inline documents); `.asta/datasets.json`, the datasets the work used,
  `[{id, name, released_by, used_for, links: [{label, url}]}]`; a theory's `gap` (written by
  `theorizer-site-data --gap G7`); a test index's `seed: {test_id, experiment}`; and a figure
  folder's `figure.json`.
- **Front matter.** `title:` and Quarto's own keys. `asta-autolink: false` turns the link
  cards off on a page.

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

{{< asta-theories data="../.asta/flows/0004-gap-driven-theory-testing/05-theories/theorizer.json"
    tests=".asta/flows/0004-gap-driven-theory-testing/06-test-designs/tests.json"
    tests_dir=".asta/flows/0004-gap-driven-theory-testing/07-tests" >}}

## Tests

{{< asta-tests dir=".asta/flows/0004-gap-driven-theory-testing/07-tests"
    index=".asta/flows/0004-gap-driven-theory-testing/06-test-designs/tests.json" >}}

{{< asta-files dir=".asta/flows/0004-gap-driven-theory-testing/07-tests" >}}
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
  shows once links to the card that lists it. `#paper-<corpus id or key>` on the theories page
  itself opens the first theory that references that paper on its Referenced papers tab and
  marks the paper there (a page that also has a paper list leaves it to the list).
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
- **Tests** (`asta-tests dir=... index=...`): a table of tests, one per subfolder of `dir`: test,
  what it tests, verdict, effect, p, animals, and links to `design.md`, the code (`test.py` or
  `code.py`), `result.md`, the summary JSON and figures; a row opens to its direction, the effect
  and p in full (for a summary that gives one per region), its figure thumbnails and its folder.
  Sortable, filterable by text and by verdict; `#test-<id>` opens a row. Files beside the test
  folders are listed under the table.
  - The summary is the folder's `result_summary.json` (else `result.json`, `results.json`). The
    verdict is its `verdict` if it states one; else `ran: false` (or `runnable: false`) is
    "not run"; `meets_threshold` true is "met", false "not met", an object of per-region
    booleans "met in X of Y" with the regions listed; anything else is "undecided" (its `status`
    shown). A folder with no summary yet is "running"; an index entry with no folder yet is
    "not started". A summary with several `subject_level_tests` and no single effect shows its
    first test with a p, and lists them all when the row is opened.
  - What a test tests comes from its index entry (`theory_name`, `title`, `hypothesis`, with
    `kind`, `dataset` and `labels` as tags); without one, from the paragraph under a
    "Hypothesis" heading in `design.md`, else its first heading.
  - `index` names one or more index files (comma-separated): a list of `{test_id, ...}`, an
    object with such a list under `tests`, or an object keyed by test id (each value an entry,
    or labels; ids without a folder are skipped). `file.json#key` reads the index under that key
    (`selection.json#groups`). Index entries come first, in their order, then folders no entry
    names. `dir` may also be a comma list.
- **Theory tests** (`asta-theories ... tests="<index>[,<index>...]"`): each index is a list of
  tests with `theory_name` and `test_id`; a test's folder is `<folder of the index>/tests/<test_id>/`
  unless `tests_dir=` names the folder that holds the test folders (one for all indexes, or a
  comma list, one per index). Tests are matched to theories by name (exactly, then ignoring
  spacing). The theory table gets a Tests column ("1 of 2 met") and each theory a Tests tab
  with each test's verdict, effect, p, animals, files and figures; tests naming no theory on the
  page are listed under the panel.

- **Datasets** (`asta-datasets`, or `file=` another file): the datasets in
  `.asta/datasets.json` as a table, Dataset, Released by, Used for, Links. It is a table of the
  page itself, so its links open their dataset cards and the test ids in "Used for" link to
  their tests.

**Files.** Every panel carries a small "Files" line linking what it was built from: the data
files (several files in one folder, or several files of one name, are their folder), a test
table's folders and indexes, an AutoDiscovery run's folder. An AutoDiscovery run's header also
links its folder and `args.json`, and an experiment from a local run its `mcts_node_*.json` and
the run's `rich_outputs/`. A paper list links each search's own file (`<name>.json`) when it is
in a `searches/` folder beside the papers file or beside its folder, or in `searches=` (from the
project root).

**Paths and links.** `data` is relative to the page, as before. The paths the file widgets name
(`dir`, `file`, `index`, `tests`, `tests_dir`, `searches`) are relative to the **project root**;
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
workspace's file. Each figure a page shows (a test's figures, an image in an `asta-doc`
document) is copied when the page renders to `_site/_asta/files/<its path in the project>`,
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
HTML, CSS and JavaScript; the panels follow the asta-theme light (cream) and dark modes. A
test's figures (their copies in the site) and the files the panels link are loaded when the
reader opens them.

**Each page's sections in the sidebar.** Under each page's sidebar link, its level-2 headings
(read from each page's source with the ids Quarto gives them, `script#asta-sections`), folded
with Quarto's chevron: the page the reader is on open, its section in view marked. "On this
page" hides while it lists just those. `asta-templates: {sidebar-sections: false}` in
`_quarto.yml` turns it off.

**Links and their cards (autolink).** Every page's links open a small card of what they
point at, and mentions of tests, theories, gaps and experiments in the text become such links:
in the review on the front page, and in the workflow pages' own prose (the inline documents
`asta-doc` shows, such as a gap map or a data inventory). The extension's filter does it, once
it is listed:

```yaml
# _quarto.yml (after the evidence filter, if the project has one)
filters:
  - _extensions/evidence/snippet.lua
  - asta-templates
```

It runs on every page (`asta-autolink: false` in a page's front matter turns it off there),
after Quarto has expanded the shortcodes and cross-references and before citations are
formatted (the extension declares `at: pre-render`). When a page renders, it reads the workflow
pages (`pages/*.qmd`), their asta-templates shortcodes and the
files those name, the site's render list (`project.render` in `_quarto.yml`), and the page's own
figures, tables, bibliography and evidence. Nothing is
fetched when a card opens: the page carries its cards once (`script.asta-cards-data`, keyed) and
each link names its card (`data-asta-card`).

| Link | Becomes a link when | Its card | A click goes to |
|---|---|---|---|
| Test id (`T3`, `node_3_1`) | a subfolder of an `asta-tests` `dir`, or an id in its `index` | verdict chip, effect, p, mice; the dataset (the index entry's `dataset`); up to four lines on the theory it tests (`theory_name`, `kind`) | the test's row, `#test-<id>` |
| AutoDS node id (`node_3_1`) | a local run's `mcts_node_3_1.json` | Discovery: "Experiment 4 · node_3_1", hypothesis, belief before → after, surprisal | `#node-3-1` |
| Theory name | a theory in an `asta-theories` file, whatever its spacing and dashes (—, –, -) | its tests as verdict chips (from the panel's `tests=` indexes), supporting and conflicting findings, its summary in up to four lines | the theory |
| Gap (`G7`) | a theory whose `gap` is that id (`theorizer-site-data --gap G7` writes it), on any theories tab | each tab with such a theory: its question in one line, how many theories, a tally of their tests ("6 tests: 1 met · 4 not met · 1 undecided"); the gap map entry (an inline document's heading or list item that starts with the id, `[G7, open] …`, which `asta-doc` anchors) | the first such tab, `#query-<n>` |
| "Experiment N" | an `asta-autods` run with experiment N (a hosted run's `id_in_run` N; a local run's node with `creation_idx` N+1; with several runs, the first; with several pages, the first by file name), except a seeded run's seed; a test index's top-level `"seed": {"test_id": …, "experiment": N}` (older indexes: a string `"<id> (Experiment N …)"`); and the hosted experiment the run was seeded from (`args.json`'s `dataset_metadata` → its `lineage`: `parent_run_id`, `seed_experiment`), or a page link to `autodiscovery.allen.ai/…?exp=N` | Discovery (the run's experiment: hypothesis, belief before → after, surprisal; the hosted experiment, with the hypothesis and beliefs of `source-experiment-N.*.json` beside the metadata) and Verification (the test) | the test, else the experiment, `<page>.html#experiment-N` (`#run-<n>/experiment-N` with several runs) |
| "Figure N", `@fig-…` | the page's `::: {#fig-…}` blocks, numbered as Quarto numbers them | a thumbnail, the caption's first sentence, n when the caption states a single `n = …`, the audit's verdict, and links to what it was made from (`figure.json`, below; without one, the verdict of an `audit.json` in the image's folder or in `.asta/flows/*/*/<fig-id>/`) | the figure |
| External link | any `http(s)` link in the text | a paper (doi.org, semanticscholar.org, or a bibliography entry's URL or DOI): title, authors, year, venue; a dataset (one of a dataset's `links` in `.asta/datasets.json`): its `name`, `released_by` and `used_for`; anything else: the site and the link's text. Always "Opens in a new tab", and the link does | the link, in a new tab |
| Citation (`[@key]`) | a bibliography entry | the quote of an evidence claim in the same paragraph citing it, then title, authors, year, venue, and Semantic Scholar and DOI links | the paper in the run's paper set, when the key (`s2-<corpus id>`, as `theorizer-site-data --bib` writes it, or a paper's key) names a paper of an `asta-literature` list (`<page>.html#paper-<corpus id or key>`), else one an `asta-theories` theory references (its page, where the first such theory opens on its Referenced papers tab); a list first, then the first page by file name; else (or a citation of several keys) the reference |
| Evidence claim (`[…]{.ev}`) | the evidence filter's popover markup | its quote, then the source as for a citation | — |
| Page of the site | a link to a `.qmd` or `.md` the site renders (in the text, or an inline document's): never a workspace file | with a fragment that names an item of that page's panels (`#experiment-N`, `#theory-N`, `#test-<id>`, `#node-<a>-<b>`, `#paper-<corpus id or key>`), that item's card, as above; without one, none | the page's `.html`, at the fragment |
| Workspace file | a link to a file of the project outside the site (in the text, or an inline document's), not a page the site renders | name, folder, size; "Opens in Files" in the app's frame, "Opens on GitHub" once a deployed site's links point there | the file |

A mention that names several things (a node id that is both the AutoDS experiment and its
reproduction test; "Experiment 7", the hosted seed and its test) links to the test, else the
theory, the experiment, the hosted experiment, the figure, the gap, and its card lists each,
with a footer saying where a click goes ("Clicking node_3_1 opens the test"); it is marked by a
dotted underline. When two pages show the same thing, the first page by file name wins. Tests,
theories, experiments and figures are linked at their first mention in a paragraph (list item,
table cell); a gap at its first mention in a section (heading to heading). A mention must stand
as a word (`node_3_1` does not link inside `node_3_12`, `G7` not inside `G7-T5`). Headings,
code, the reference list and Quarto's navigation text are left as they are. `asta-doc` gives a
list item or heading that starts with an id (`G1 …`, `[G1, open] …`) the anchor
`doc-<file>-<id>`, which a gap's card links.

**What a figure was made from (`figure.json`).** A figure's folder may carry a `figure.json`:

```json
{"id": "fig-drift", "script": "make_figure.py", "inputs": [".asta/flows/0003-x/06-findings/calibration.json"], "audit": "audit.json"}
```

`script` and `audit` are relative to that folder, `inputs` to the project root. The folder is the
image's own, a step folder named for the figure (`.asta/flows/*/*/<fig-id>/`), or any step
folder whose `figure.json` gives the figure's `id`. Under each such figure the extension's
`provenance.lua` filter (it runs before Quarto turns `::: {#fig-…}` blocks into figures,
`at: pre-ast`) adds a small line: "Made from make_figure.py · 3 inputs · audit PASS", each part a
link to its file, written relative to the rendered page (so it opens in the app's Files tab, or
on GitHub once a deployed site's links point there); "3 inputs" opens to list each input with
its folder. A figure made of sub-figures gets one line with an entry per sub-figure that has a
`figure.json`, "(a) …; (b) …". A figure without one gets nothing. A file the `figure.json` names
that does not exist is a render warning and is shown as "(missing)", never as a link. The
figure's card links the same files: the script, the first three inputs ("+N more" opens the
folder), and the audit.

**The cards.** One renderer (`asta-templates.js`) draws every card from the same parts: sections,
each with any of a role, a linked title, a sub line, a thumbnail, a quote, text clamped to some
lines, a test's verdict, tests' verdict chips, a tally, facts and links, then a footer. A new
kind of link needs an adapter in `autolink.lua` that returns such a card, and no card code.
Hovering a link, focusing it or tapping it opens its card beside it, below or above, never over
it, the size of a short note (380 px at most); the card stays while the pointer is on it and
closes when the pointer has left both for a moment, on Esc (focus back on the link) or on a
click elsewhere; Tab from the link goes into the card; on a touch screen a first tap opens the
card and a second follows the link. A link with a card has no native `title`, and Quarto's own
reference and cross-reference previews are switched off on it, so one hover shows. The cards
take the theme's colours (light and dark), and work in the app's site frame and on GitHub Pages. An AutoDS hypothesis, a theory's name and summary, and the theory a test belongs to show up to four lines (`DESCRIPTION_LINES` in `autolink.lua`).

**With the evidence extension.** Evidence keeps owning the claims and their quotes (its filter
writes them as a hidden popover, `.ev > .ev-pop`, shown with CSS). The asta-templates filter runs
after it and reads that markup; where it gives a claim a card, `asta-templates.js` marks the page
(`html.asta-cards`) and `asta-templates.css` keeps evidence's popover shut on those claims. Without
asta-templates, or where its script does not run (the what-changed diff page), evidence's popover
shows as before.

`make workspace-assets` fetches this extension when a page uses one of its shortcodes, like the
evidence extension. To customize it, commit a copy of `_extensions/asta-templates` and remove its
line from `.gitignore`.
