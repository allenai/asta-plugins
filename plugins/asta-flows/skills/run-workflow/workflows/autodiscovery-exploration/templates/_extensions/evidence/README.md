# evidence — supporting quotes for claims

A small, self-contained bundle that lets any factual claim in Quarto prose carry
the evidence that backs it. The claim stays plain text, and a short bracketed
**marker** after it — `[J-6]` for an AutoDiscovery experiment, or the work's own
citation such as `[1]` — opens a small popover on hover, keyboard focus or tap.
The popover holds a **verbatim quote** from the source and the work's **full
reference** (formatted like the reference list, with the locator and a Semantic
Scholar link). The quotes live in an external keyed store (`evidence.yml`) so
the prose stays editable, and the rendered popover shows up in the
`what-changed` diff for review.

Scaffolded by the asta-plugins **`workspace` skill** into a research project, so
every rendered report can back its claims the same way — an agent that writes a
claim it looked up (e.g. via `asta papers snippet-search`) can attach the exact
supporting quote and its citation, opened from the marker and reviewable in the
diff.

The unit is deliberately small and timeless: **a claim → a verbatim quote → a
reference with a locator.** Provenance (how the quote was obtained) is retained
but kept out of the way (see below).

## Usage

### Keyed store (recommended) — keep the prose readable

Put the evidence in an external YAML store, keyed, and reference it from the
prose with a short `key`. This keeps the `.qmd` editable — a claim carries only
`{.ev key="…"}`, not a wall of `quote="…"` — while the (often long) quotes and
citations are edited and reviewed in one structured file.

In `evidence.yml`:

```yaml
evidence:
  naturebench-count:
    quote: "a cross-discipline benchmark of 90 tasks distilled from peer-reviewed Nature-family publications"
    cite: naturebench2026
    locator: abstract
```

Wire it into the project once, in `_quarto.yml`, so the filter can read it from
document metadata:

```yaml
metadata-files:
  - evidence.yml
```

Then reference the key in the prose:

```markdown
NatureBench has [90 tasks]{.ev key="naturebench-count"} [@naturebench2026].
```

The claim renders as plain text and the citation after it becomes the marker
(see [Markers](#markers)).

Because the evidence lives in its own file, a review sees claim-vs-key changes in
the `.qmd` diff and quote-text changes isolated in `evidence.yml` — and the
rendered popover (and its `what-changed` hover) is identical to the inline form.

### Inline (for one-offs / overrides)

For a single claim that doesn't warrant a store entry, give the evidence inline.
Provide a verbatim `quote` plus a `cite` key (or a free-text `source`):

```markdown
NatureBench has [90 tasks]{.ev
  quote="a cross-discipline benchmark of 90 tasks distilled from peer-reviewed Nature-family publications"
  cite="naturebench2026"
  locator="abstract"}.
```

Inline attributes may also be combined with `key=` to override a single stored
field for one claim; inline wins field by field.

| attribute | required | meaning |
|---|---|---|
| `quote`   | yes | a **verbatim** quotation from the source — rendered in “curly quotes” and italic so the reader can see it is exact wording |
| `cite`    | no | a bibliography key from `references.bib`; rendered as a real citation in the **same author–year format used in the body text**, linked to the reference entry |
| `source`  | no | free-text citation for a source that has no bib key |
| `url`     | no | link for a `source` that has no bib key |
| `page`    | no | a page on this site for the `source`, as a path relative to the page (like `image`): the source text links to it in the same tab, and `url` becomes a separate "open ↗" link after it |
| `locator` | no | a **native Pandoc/citeproc locator** appended to the citation — see below |
| `label`   | no | the marker's text, e.g. `J-6` (shown as `[J-6]`); see [Markers](#markers) |
| `image`   | no | a figure from the source, shown at the top of the popover and linked to the full-size file: a path relative to the page (like any figure) or an `http(s)` URL |
| `image_alt` | no | the figure's alt text; defaults to "Figure from" and the source |

Everything shown is a **verbatim quote**; there is no "paraphrase" mode. If you
want to state something in your own words, just write it in the prose — the
evidence popover is for exact source wording only. This keeps the concept small
and unambiguous.

**Same reference format as the document.** A `cite=` key is formatted by
citeproc with the document's own bibliography and CSL: the marker is the same
citation an inline `[@key]` gives, and the popover shows the work's full
reference exactly as the reference list does (see
[Full references](#full-references)).

Inside a Markdown **pipe table**, keep the attribute text free of the `|`
character (it would end the cell). Everything else — commas, parentheses, `>`,
math around the span — is fine.

## Markers

The claim reads as plain text; a short marker right after it (joined to the
claim's last word by a no-break space) opens the evidence. The marker reads like
a citation: link colour, underlined only on hover or focus, never split across a
line, and never a chip or pill. On touch screens an invisible, larger hit area
makes it easy to tap without changing the line, and the popover opens as a
sheet along the bottom of the screen.

The marker's text is, in order:

1. the entry's `label`, in brackets: `label: N-1` gives `[N-1]`;
2. derived from an AutoDiscovery `source`: "AutoDiscovery run J, experiment 6"
   gives `[J-6]` and "AutoDiscovery run J (…)" gives `[J]`;
3. for a `cite` entry, the work's own citation, formatted by citeproc like any
   other citation in the document (`[1]`, or `(Vaswani et al. 2017)` in an
   author-date style);
4. otherwise `[source]`.

A citation of the same work immediately after the claim becomes the marker, so
the work is not cited twice: `[claim]{.ev key="k"} [@key, p. 7]` renders the
claim, then that citation (with its own locator) as the marker. A narrative
citation (`@key says`) belongs to the next sentence and stays where it is. A
span whose text equals its label is itself the marker, which suits a list of
experiments: `Experiments [J-6]{.ev key="ad-j-6"} and [J-7]{.ev key="ad-j-7"}`.
Quarto's own reference tooltip is removed from citations inside markers and
popovers, since the marker already opens the evidence.

With `evidence-marker: claim` the claim itself opens the evidence instead: it
gets a subtle dotted underline (`evidence-underline: hover` hides even that
until the reader points at it), and nothing is added after it.

## Full references

A `cite` entry's popover shows the work's full reference, formatted by citeproc
with the document's own bibliography and CSL, as in the reference list (without
the list's number). Below it, on a line of its own, are the locator and a
**Semantic Scholar** link,
`https://api.semanticscholar.org/CorpusID:<id>` (which redirects to the paper's
page), built from any entry's `provenance.corpus_id` for that work. Citeproc
runs once for all cited works; if it fails, the popover falls back to the short
citation and the render prints a warning. A work cited only inside a popover
stays in the reference list. `evidence-reference: short` shows the short
citation instead, as in the body text.

Every link to a source — the reference's DOI or URL, the Semantic Scholar link,
a `source`'s `url`, a figure, and the links under "Source details" — opens in a
new tab, so the reader keeps their place in the text.

## Figures

When the source has a figure that shows the quoted result, such as a plot from
an analysis, give its path in `image`. The figure sits at the top of the
popover, scaled to the card's width (the card widens to 480 px), and links to
the full-size file. On phones it spans the bottom sheet, which scrolls. The
path is relative to the page that cites the claim, as for any figure, so keep
claims with figures on pages in one directory. Quarto copies only the files a
page references through its own markup, so list the figures under `project:
resources:` in `_quarto.yml` (for example `figures/**/*.jpg`). Keep figures
small, because a page loads them with its popovers.

```yaml
evidence:
  experiment-47:
    quote: "survey-weighted seronegativity was 7.17% for Type 1 …"
    source: "AutoDiscovery run B, experiment 47"
    url: https://autodiscovery.allen.ai/runs/shared/…?exp=47
    image: figures/b-47.jpg
    image_alt: "Seronegativity by serotype among tetanus-seropositive children"
```

`evidence-figures: false` leaves every figure out of the popovers, for a site
whose readers find them too busy; the `image` fields stay in `evidence.yml`.

## Pages on this site

A source can have its own page on the site as well as a hosted link, such as an
AutoDiscovery run's page beside the hosted experiment. Give the page in `page`:
the source line then links "AutoDiscovery run A, experiment 40" to that page, in
the same tab, and `url` follows as a separate "open ↗" link in a new tab. Like
`image`, the path is relative to the page that cites the claim.

```yaml
evidence:
  dps-a-40:
    quote: "Among children who successfully seroconverted to both Type 1 and Type 2 …"
    source: "AutoDiscovery run A, experiment 40"
    url: https://autodiscovery.allen.ai/runs/shared/…?exp=40
    page: runs/assay.qmd
```

## Options

Document metadata keys change how claims and popovers look. Set them at the
top level of `_quarto.yml` for a whole site, or in a page's front matter:

| key | default | other value |
|---|---|---|
| `evidence-marker` | `label`: the claim stays plain text and a short marker after it opens the evidence ([Markers](#markers)) | `claim`: the claim itself opens the evidence on hover or focus, with a dotted underline |
| `evidence-reference` | `full`: the work's full reference, the locator and a Semantic Scholar link ([Full references](#full-references)) | `short`: the short citation the body text uses, with the locator |
| `evidence-provenance` | `true`: an entry's provenance sits behind a collapsed "Source details" disclosure | `false`: no disclosure; provenance stays in `evidence.yml` (to hide it for some entries only, leave `provenance` out of them) |
| `evidence-figures` | `true`: an entry's `image` sits at the top of its popover ([Figures](#figures)) | `false`: no figures in popovers |
| `evidence-underline` | `always`: with `evidence-marker: claim`, a dotted underline marks each claim | `hover`: claims read as plain prose until hovered, focused or open; it has no effect on markers |

An unrecognised value prints a warning and keeps the default.

## Locators — use Pandoc's native format, don't re-invent one

Pandoc/citeproc already has a **citation locator** syntax: the part after the
comma in `[@key, p. 4]`. citeproc understands the standard locator labels and
formats them in the active citation style (e.g. Chicago author-date renders a
bare page as a number, and `sec. 3.2` as "sec. 3.2"). The `locator` field is fed
straight into that mechanism (the filter puts it in the citation's suffix), so we
inherit citeproc's formatting instead of inventing our own. That is how the
short citation (`evidence-reference: short`) shows it; a full reference shows
the locator as written, on the line beneath it:

```yaml
locator: "p. 4"        # → (Author 2026, 4)
locator: "pp. 4-6"     # → (Author 2026, 4–6)
locator: "sec. 3.2"    # → (Author 2026, sec. 3.2)
locator: "chap. 2"     # → (Author 2026, chap. 2)
locator: "abstract"    # → (Author 2026, abstract)   (free label passes through)
```

Recognised labels include `book`/`bk.`, `chapter`/`chap.`, `column`/`col.`,
`figure`/`fig.`, `folio`/`fol.`, `line`/`l.`, `note`/`n.`, `opus`/`op.`,
`page`/`p.`/`pp.`, `paragraph`/`para.`, `part`/`pt.`, `section`/`sec.`,
`sub verbo`/`s.v.`, `verse`/`v.`, `volume`/`vol.`. Omit `locator` when you have no
precise page or section (e.g. a full-text body snippet with no returned section).

## Provenance — retained, but not shown by default

Backing a claim with a quote answers *what* supports it; **provenance** records
*how that support was obtained*, when that is known. A store entry can carry a nested
`provenance:` map. It is **recorded in `evidence.yml` (and so is diff-reviewable)
but not shown by default** in the popover — the primary view is just the quote
and its reference. Provenance sits behind a small **“Source details”** disclosure
(built from plain inline spans, revealed with pure CSS on hover/focus — no
JavaScript) so it is one interaction away without turning the popover into a wall
of metadata; `evidence-provenance: false` drops the disclosure. A `corpus_id`
also gives the work's full reference its Semantic Scholar link, for every entry
that cites that work.

```yaml
evidence:
  # The retrieval command was not recorded, so method is omitted.
  naturebench-count:
    quote: "a cross-discipline benchmark of 90 tasks distilled from …"
    cite: naturebench2026
    locator: abstract
    provenance:
      corpus_id: 289622360
      retrieved: 2026-08-29

  # Surfaced by a real Asta snippet search — the query is preserved so the
  # retrieval is reproducible. These entries are real: produced by running
  # `asta papers snippet-search "<query>"` and keeping the `body` hits whose
  # `paper.corpusId` is the source paper. That is how the design is verified to
  # scale beyond abstracts — the quote here is a full-text body snippet.
  naturebench-domains:
    quote: "Across 90 tasks, NatureBench spans six scientific domains …"
    cite: naturebench2026
    provenance:
      method: asta papers snippet-search
      query: "NatureBench NatureGym containerized environment scientific discovery agent"
      corpus_id: 289622360
      retrieved: 2026-08-29
```

The schema is deliberately **small and open**, but its values should be narrow:
record the exact producer invocation (for example, `asta papers snippet-search`),
not a skill name or broad category. If a tool output is indexed by Asta Documents,
store the canonical `asta://` URI it returns in `url`; do not invent another
artifact name or duplicate metadata encoded by that URI. Every field is optional:
when the retrieval route was not recorded, omit `method` rather than infer it.

| provenance field | meaning |
|---|---|
| `method` | exact producer invocation, such as `asta papers snippet-search`; omit when unknown |
| `query` | the search query that surfaced the quote (search methods) |
| `corpus_id` | S2 corpusId of the source paper (the reference's Semantic Scholar link, and an S2 link under "Source details") |
| `url` | canonical `http:`, `https:`, or `asta:` source/document URI |
| `retrieved` | ISO date the evidence was obtained |
| `note` | free text |

Deliberately **not** modelled (kept out to stay timeless): a paraphrase mode,
snippet char-offsets/scores/section labels, and a per-artifact `kind` enum. Those
were speculative; when a real need appears, add the one field it needs.

## How it works

Three files, no framework dependency (works under any Quarto theme):

- `snippet.lua` — a Pandoc filter that adds the marker after the claim and
  gives it a **real hidden child span** (`.ev-pop`) holding an optional figure
  (a raw `<img>`, so Quarto adds no figure or lightbox wrapper), the
  typographic-quoted verbatim quote, the work's full reference (or, with
  `evidence-reference: short`, an injected `Cite` with the locator in its
  suffix so citeproc formats it), and an inline **“Source details”** disclosure
  for provenance. Everything in the popover
  is **phrasing (inline) content only** — no `<details>`/`<div>`/block element —
  see "Surviving the what-changed diff" for why that matters. It makes the
  marker focusable and mirrors the quote + reference into `aria-description`
  for assistive tech. For non-HTML output it is a no-op, so the claim text
  still renders.
- `evidence.head.html` — the marker and dotted-underline styles and the popover
  styling. The
  popover is shown **purely with CSS** (`.ev:hover > .ev-pop`,
  `.ev:focus-within > .ev-pop`) — no JavaScript needed for it to appear. On
  touch screens and windows narrower than 768 px it opens as a sheet fixed to
  the bottom of the viewport; a tap focuses the marker, which opens it. While
  hidden, a popover is moved above and left of its claim so it never widens the
  page.
- `evidence.body.html` — a tiny **optional** progressive-enhancement script that
  flips the popover leftward when it would spill past the right edge of the
  viewport, closes an open popover when the reader taps elsewhere (not every
  mobile browser moves focus on a tap on plain text), and removes Quarto's
  reference tooltip from citations in markers and popovers. Everything works
  without it.

### Reliable hover (no gap, no timers)

The popover is a **DOM descendant** of the claim, and CSS `:hover` applies to an
element while any descendant is hovered. So moving the pointer from the claim
onto the popover keeps `.ev:hover` true and the popover stays open — there is no
"gap" between claim and box that can dismiss it, and no JavaScript hover timers
to misfire. A transparent top-padding "bridge" on `.ev-pop` covers the small
visual gap to the claim so the pointer never crosses a dead zone.

A claim that **wraps onto several lines** (common in a narrow table cell) has
tiny leading gaps *between* its line boxes where `:hover` is momentarily false.
To stop the popover flashing off and back on as the pointer brushes across those
gaps, hiding is **delayed by a short grace period** (`transition-delay` on the
non-hover state) while showing stays immediate: the pointer re-enters the next
line well inside the window, so the hide transition never starts. The grace is
kept modest so moving to a *different* claim doesn't leave two popovers
overlapping for long.

## Surviving the what-changed diff

The workspace preview's **`what-changed.html`** is generated by a sanitizer that
strips every embedded page's `<script>` and every non-allowlisted attribute (so
two embedded reports can't collide on ids or globals). Crucially, its allowlist
**keeps** `class`, `role`, `title`, `aria-*`, `<a href>` (and
`target="_blank"`, with its own `rel`), and `<img src alt loading>`, and the
generator
**re-embeds the site's head `<style>`** (pulled from the template page). Because
the evidence popover is made of exactly those survivors — plain spans with
classes, real `<a href>` links, and CSS in the head — the whole popover (styled
box, quote formatting, full reference and links, disclosed provenance) renders
on the diff page with **no JavaScript at all**, driven by the surviving `:hover`
CSS. The diff styles a marker like its other links (link colour and weight, no
resting underline) and strengthens a claim's dotted underline in claim mode.

**The popover must be inline (phrasing) content only.** The diff wraps an inserted
claim in `<ins>` and a deleted one in `<del>`. If the popover contained a
block-level element (`<details>`, `<div>`, `<p>`), the diff would have to emit a
`</ins>` *before* that block while the popover's `<span>`s are still open; the
HTML parser resolves that stray `</ins>` by closing those spans too, **ejecting
the block out of the hidden popover** so it renders as stray visible text (and
strands fragments the diff's block-folder then mis-collapses) — most visibly
inside a table cell. Keeping the whole popover a single valid **phrasing subtree**
(spans + `<a>` + `<em>`, disclosure done with CSS not `<details>`) means the
inserted claim is one balanced inline run the diff highlights atomically, so the
popover survives intact. Verified end-to-end by rendering the site, running the
real workspace `what-changed.py`, and asserting (via a headless DOM) that on the
generated diff every popover — quote, citation, and “Source details” — stays a
descendant of the hidden `.ev-pop`, nothing leaks into the cell, and the folder
never collapses popover content.

## Wiring

The workspace scaffold fetches this directory from `asta-plugins` before each
render and wires it in `_quarto.yml` (see the `workspace` skill). The generated
directory is ignored rather than committed. By default the render-time fetch
uses the latest release tag; projects can set `ASTA_PLUGINS_REF=main` to trial
the in-flight extension. To wire it by hand into an existing project, add:

```yaml
metadata-files:
  - evidence.yml          # the keyed quote store (create an empty one to start)

filters:
  - _extensions/evidence/snippet.lua

format:
  html:
    include-in-header:
      - _extensions/evidence/evidence.head.html
    include-after-body:
      - _extensions/evidence/evidence.body.html
```

The store path is a convention, not a requirement: point `metadata-files` at
wherever you keep the `evidence:` map (e.g. `docs/evidence.yml` if your `.qmd`s
live under `docs/`). The filter reads the merged `evidence:` metadata regardless
of the file's location.

## Design choices

- **Small and timeless.** One evidence unit = a verbatim quote + a reference +
  an optional locator. No paraphrase mode, no speculative provenance vocabulary.
- **Native locators.** Reuse Pandoc/citeproc's own locator syntax rather than
  inventing a `§`/offset convention, so locators format in the site's style.
- **Provenance retained, not loud.** How a quote was obtained is kept in
  `evidence.yml` and available behind a small inline “Source details” disclosure —
  auditable, not overwhelming.
- **Inline-only popover.** The popover is entirely phrasing content (no
  `<details>`/block element), so it stays one valid inline subtree that survives
  the `what-changed` diff's `<ins>`/`<del>` wrapping intact.
- **Markers read like citations.** The claim is never styled; the marker after
  it is link-coloured text with no chip, border, background or padding, so a
  paragraph with several markers still reads as prose. Claim mode's dotted
  underline is the subtle alternative, and `evidence-underline: hover` removes
  even that until the reader points at a claim.
- **CSS-first, one code path.** The popover is revealed with CSS on both the site
  and the diff page, so behaviour doesn't diverge; JS is optional edge-flip only.
- **No framework, accessible.** A hand-rolled popover portable to any theme;
  markers (or claims) are `tabindex=0` / `role="note"`, open on focus as well as
  hover, and carry the quote and citation key in `aria-description` for screen
  readers.
  The full report supports keyboard focus; the current `what-changed` sanitizer
  strips `tabindex`, so its embedded diff view is hover-only.
