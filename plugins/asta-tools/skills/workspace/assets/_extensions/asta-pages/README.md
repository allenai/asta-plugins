# asta-pages — theory and paper pages for a run

Shortcodes that turn a run's files into page panels, the way the Asta app shows Theorizer's
results:

```markdown
{{< asta-theories data="data/theorizer.json" >}}    <!-- the Theorizer panel -->
{{< asta-theories data="data/theorizer.json,data/theorizer-v2.json" >}}  <!-- several projects -->
{{< asta-literature data="data/papers.json" >}}     <!-- the paper list -->
{{< asta-workflow >}}                               <!-- workflow.mmd beside the page, if any -->
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
- **Workflow:** the Mermaid diagram in `workflow.mmd` (or `file="..."`) under a "Workflow"
  heading, drawn by the Mermaid runtime that Quarto ships, copied into the site. With no file it
  renders nothing, so a page can carry it before a diagram exists.

`data` is relative to the page. The file is read at render time and embedded in the page, so the
page makes no request at view time. A
missing or unreadable file renders a visible error box and a render warning. Anchors: `#theory-2` selects a theory, `#finding-<uuid>` opens the Evidence tab
at that row, `#query-2` selects a query's tab, `#paper-<corpus id>` scrolls to a paper.

The data files are written by the run-workflow skill's theory-generation workflow
(`workflows/theory-generation/scripts/theorizer-site-data`), from a `theorize` project; each
theory carries its `query`. A second project's file (`data/theorizer-v2.json`) gets its own
papers file beside it (`data/papers-v2.json`), leaving the first one's `papers.json` as it is. Plain
HTML, CSS and JavaScript; the panels follow the asta-theme light (cream) and dark modes.

`make workspace-assets` fetches this extension when a page uses one of its shortcodes, like the
evidence extension. To customize it, commit a copy of `_extensions/asta-pages` and remove its
line from `.gitignore`.
