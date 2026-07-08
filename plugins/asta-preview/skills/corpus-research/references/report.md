# The REPORT — the user-facing deliverable of a run

Disambiguation (three things people conflate):
- **Report** = THE user-facing browsable deliverable. One entry point, self-contained, portable.
  It is a FILE first (markdown set + an HTML explorer) — packageable, emailable, re-sendable.
- **Run artifacts** = workspace files (candidates, judgments, substrate, caches). Never shown AS
  the deliverable; the report LINKS INTO them ("every number traces to a file you can open").
- **Harness/publishing artifacts** (e.g. a hosted page) = optional PUBLISHING CHANNELS for the
  report, not the report. Do NOT source the report's structure from generic artifact-design
  guidance — this file is the spec.

## Content requirements (each traces to a real reader complaint or a real run's win)
1. **One index page / README**: what this is, corpus size + as-of date + refresh trigger, links
   to every deliverable, a read-order, and honest notes. Readers start here.
2. **Per-question method notes** — every answered sub-question carries its own "How performed"
   note (corpus + ring + method + evidence tier + limits). A global methods blurb does not count.
3. **Every paper reference is a working link** (see answers.md — HARD requirement).
4. **Evidence in the body.** When the ask says "extract the paragraphs/passages", the verbatim
   spans appear IN the report (linked to source), never only in data files. A reader who asked
   for paragraphs and finds tallies experienced an omission, whatever the data files contain.
5. **Per-paper catalog view** grouped by the derived families, with tier/tags and a one-line
   grounded claim per paper — the view readers use to judge the corpus itself.
6. **Honest coverage section**: verdict + estimators-used-vs-gated + explicit boundary + "what
   not to assume." Numbers trace to the coverage files.
7. **Distribution visuals per deliverable, data-generated.** Each question's view opens with its
   distribution(s) — family/tier breakdowns, per-axis stance splits (both sides, with n),
   modality yields on the coverage page. Charts are GENERATED from the data files (a script →
   chart-data JSON → inline SVG), never hand-coded numbers — charts are where numbers silently
   drift from data. Each chart captioned with what it counts and its n. In-section panels, not a
   separate charts layer.
8. **Self-contained rendering**: no external CDNs/scripts/fonts; everything inline. Works
   offline, works emailed, works on any hosted channel.
9. **The package**: report + final data files (observations / extractions / relevance + a CSV
   for spreadsheet readers) + README with read-order and honest caveats — the package is what
   actually gets SENT.
10. **Engagement is a feature** — interactive embeds (sortable catalog, filters, expandable
    evidence) are worth their cost IF grounded in the data files; a browsable report is what
    non-operators actually read.
11. **Every prose aggregate has a data-file home.** Any count/percentage quoted in report prose
    must exist in a shipped data file (ship the aggregate you quote; coverage-verdict numbers
    live in coverage files). Audited: a real report's per-family adoption counts existed only in
    prose — untraceable = unreviewable. `report_trace`-style checking should find ~0 orphans.
