# evidence — hover-viewable supporting quotes for claims

A small, self-contained bundle that lets any factual claim in Quarto prose carry
the evidence that backs it. The claim gets a **subtle light dotted underline**;
hovering (or keyboard-focusing) it reveals a small popover with a **verbatim
quote** from the source and a **reference** (in the page's own citation style,
with an optional locator). The quotes live in an external keyed store
(`evidence.yml`) so the prose stays editable, and the rendered popover shows
up in the `what-changed` diff for review.

Scaffolded by the asta-plugins **`workspace` skill** into a research project, so
every rendered report can back its claims the same way — an agent that writes a
claim it looked up (e.g. via `asta papers snippet-search`) can attach the exact
supporting quote and its citation, viewable on hover and reviewable in the diff.

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
NatureBench has [90 tasks]{.ev key="naturebench-count"}.
```

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
| `url`     | no | link for a `source` that has no bib key (opens in a new tab) |
| `locator` | no | a **native Pandoc/citeproc locator** appended to the citation — see below |

Everything shown is a **verbatim quote**; there is no "paraphrase" mode. If you
want to state something in your own words, just write it in the prose — the
evidence popover is for exact source wording only. This keeps the concept small
and unambiguous.

**Same reference format as the body.** A `cite=` key is turned into a real Pandoc
`Cite` by the filter *before* Quarto's citeproc runs, so it resolves to exactly
the `(Author Year)` citation (and `#ref-` link) the surrounding prose uses — the
popover's reference looks identical to an inline `[@key]` in the text.

Inside a Markdown **pipe table**, keep the attribute text free of the `|`
character (it would end the cell). Everything else — commas, parentheses, `>`,
math around the span — is fine.

## Locators — use Pandoc's native format, don't re-invent one

Pandoc/citeproc already has a **citation locator** syntax: the part after the
comma in `[@key, p. 4]`. citeproc understands the standard locator labels and
formats them in the active citation style (e.g. Chicago author-date renders a
bare page as a number, and `sec. 3.2` as "sec. 3.2"). The `locator` field is fed
straight into that mechanism (the filter puts it in the citation's suffix), so we
inherit citeproc's formatting instead of inventing our own:

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

Backing a claim with a quote answers *what* supports it; **provenance** answers
*how that support was obtained* — was the quote returned by an Asta snippet
search, or read straight out of the paper? A store entry can carry a nested
`provenance:` map. It is **recorded in `evidence.yml` (and so is diff-reviewable)
but not shown by default** in the popover — the primary view is just the quote
and its reference. Provenance sits behind a small **“Source details”** disclosure
(built from plain inline spans, revealed with pure CSS on hover/focus — no
JavaScript) so it is one interaction away without turning the popover into a wall
of metadata.

```yaml
evidence:
  # Read directly from the paper's abstract.
  naturebench-count:
    quote: "a cross-discipline benchmark of 90 tasks distilled from …"
    cite: naturebench2026
    locator: abstract
    provenance:
      method: paper
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
      method: asta-snippet-search
      query: "NatureBench NatureGym containerized environment scientific discovery agent"
      corpus_id: 289622360
      retrieved: 2026-08-29
```

The schema is deliberately **small and open**: `method` is free text and every
field is optional, rendered only when present. An unrecognised `method` renders
its own string as the label. That is enough to grow to new kinds of derived
evidence *without committing now to fields we don't yet need*: a claim backed by
a **theorizer** run points `url` at the report's citable URI (an `asta://…`
document URI from `asta documents`, or the A2A task-artifact URL that
`asta artifacts` exports) and sets `method: theorizer` — no schema or filter
change:

```yaml
  some-derived-claim:
    quote: "…exact wording from the produced report…"
    provenance:
      method: theorizer
      url: asta://reports/run-8f2c   # citable URI — no need to commit the artifact
      retrieved: 2026-08-29
```

| provenance field | meaning |
|---|---|
| `method` | how it was obtained — `paper`, `asta-snippet-search`, `theorizer`, … (any string; known values get a friendlier label) |
| `query` | the search query that surfaced the quote (search methods) |
| `corpus_id` | S2 corpusId of the source paper (rendered as an S2 link) |
| `url` | canonical `http:`, `https:`, or `asta:` link to the source or a produced artifact/report URI |
| `retrieved` | ISO date the evidence was obtained |
| `note` | free text |

Deliberately **not** modelled (kept out to stay timeless): a paraphrase mode,
snippet char-offsets/scores/section labels, and a per-artifact `kind` enum. Those
were speculative; when a real need appears, add the one field it needs.

## How it works

Three files, no framework dependency (works under any Quarto theme):

- `snippet.lua` — a Pandoc filter that appends a **real hidden child span**
  (`.ev-pop`) to the claim, holding the typographic-quoted verbatim quote, an
  injected `Cite` (with the locator in its suffix so citeproc formats it), and an
  inline **“Source details”** disclosure for provenance. Everything in the popover
  is **phrasing (inline) content only** — no `<details>`/`<div>`/block element —
  see "Surviving the what-changed diff" for why that matters. It makes the claim
  focusable and mirrors the quote + reference into `aria-description` for
  assistive tech. For non-HTML output it is a no-op, so the claim text still
  renders.
- `evidence.head.html` — the dotted-underline style and the popover styling. The
  popover is shown **purely with CSS** (`.ev:hover > .ev-pop`,
  `.ev:focus-within > .ev-pop`) — no JavaScript needed for it to appear.
- `evidence.body.html` — a tiny **optional** progressive-enhancement script whose
  only job is to flip the popover leftward when it would spill past the right
  edge of the viewport. Everything works without it.

### Reliable hover (no gap, no timers)

The popover is a **DOM descendant** of the claim, and CSS `:hover` applies to an
element while any descendant is hovered. So moving the pointer from the claim
onto the popover keeps `.ev:hover` true and the popover stays open — there is no
"gap" between claim and box that can dismiss it, and no JavaScript hover timers
to misfire. A transparent top-padding "bridge" on `.ev-pop` covers the small
visual gap to the claim so the pointer never crosses a dead zone.

## Surviving the what-changed diff

The workspace preview's **`what-changed.html`** is generated by a sanitizer that
strips every embedded page's `<script>` and every non-allowlisted attribute (so
two embedded reports can't collide on ids or globals). Crucially, its allowlist
**keeps** `class`, `role`, `title`, `aria-*`, and `<a href>`, and the generator
**re-embeds the site's head `<style>`** (pulled from the template page). Because
the evidence popover is made of exactly those survivors — plain spans with
classes, a real `<a href="#ref-…">` citation link, and CSS in the head — the whole
popover (styled box, quote formatting, working citation link, disclosed
provenance) renders on the diff page with **no JavaScript at all**, driven by the
surviving `:hover` CSS.

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

The workspace scaffold wires this in `_quarto.yml` for you (see the `workspace`
skill). To wire it by hand into an existing project, add:

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
- **Subtle by default.** The affordance is a 1px dotted underline at ~32% opacity
  — visible if you look for it, not distracting while reading.
- **CSS-first, one code path.** The popover is revealed with CSS on both the site
  and the diff page, so behaviour doesn't diverge; JS is optional edge-flip only.
- **No framework, accessible.** A hand-rolled popover portable to any theme;
  claims are `tabindex=0` / `role="note"`, open on focus as well as hover, and
  carry the quote and citation key in `aria-description` for screen readers.
  The full report supports keyboard focus; the current `what-changed` sanitizer
  strips `tabindex`, so its embedded diff view is hover-only.
