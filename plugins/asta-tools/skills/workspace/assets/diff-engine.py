#!/usr/bin/env python3
"""The diff engine behind the "What changed" page.

Parses rendered page content into tokens, aligns the old and new tokens, and
marks added and removed words and inline formatting with `<ins>`/`<del>` so the
result stays valid HTML; also holds the diff's styles (DIFF_STYLE) and the
client-side script that folds long unchanged stretches (FOLD_JS).

what-changed.py loads this file from its own directory; a page that only needs
the diff can load it alone. Pure standard library.
"""

import difflib
import hashlib
import re
from collections import Counter

# Inline formatting tags may live *inside* an <ins>/<del>; anything else is
# treated as structural and closes the wrapper so we never nest a block element
# inside <ins>/<del> where its parent won't allow it (e.g. <ins> as a child of
# <ul>).
INLINE_TAGS = {
    "a",
    "abbr",
    "b",
    "bdi",
    "bdo",
    "br",
    "cite",
    "code",
    "data",
    "dfn",
    "em",
    "i",
    "kbd",
    "mark",
    "q",
    "s",
    "samp",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "time",
    "u",
    "var",
    "wbr",
    "img",
}

TOKEN_RE = re.compile(r"<[^>]+>|[^<]+")
WORD_RE = re.compile(r"\s+|[^\s]+")
TAG_NAME_RE = re.compile(r"</?\s*([a-zA-Z0-9]+)")


def tokenize(content):
    """Split HTML into a flat list of (kind, text) tokens.

    kind is 'tag' for markup, 'word' for a non-whitespace run, 'space' for a
    whitespace run. Words/tags are what the diff aligns on; spaces ride along
    with the neighbouring op so wrapping stays tight.
    """
    tokens = []
    for chunk in TOKEN_RE.findall(content):
        if chunk.startswith("<"):
            tokens.append(("tag", chunk))
        else:
            for w in WORD_RE.findall(chunk):
                tokens.append(("space" if w.isspace() else "word", w))
    return tokens


def tag_name(tok):
    m = TAG_NAME_RE.match(tok)
    return m.group(1).lower() if m else ""


def is_inline_tag(tok):
    return tag_name(tok) in INLINE_TAGS


EV_CLAIM_RE = re.compile(
    r"""(?is)<span(?=\s|>)[^>]*?\sclass\s*=\s*(["'])(?:[^"']*\s)?ev(?:\s[^"']*)?\1"""
)


def is_ev_claim(tok):
    """An evidence claim's own `<span class="ev">`: structural, never wrapped
    in <ins>/<del>, so its popover stays the direct child the hover CSS needs."""
    return bool(EV_CLAIM_RE.match(tok))


def balanced_inline(tokens):
    """Indices of inline tags whose matching partner is inside this same run.

    An inline pair (`<strong>`…`</strong>`) that is only *partly* inside a
    changed run — the open tag changed but its close sits in unchanged content,
    or vice versa — cannot be highlighted without producing a lone tag inside
    an <ins>/<del> (e.g. `<ins><strong></ins>`), which is invalid markup even
    if browsers recover from it. Such half-in tags are excluded here so
    emit_run treats them as structural (emitted bare / dropped) instead.
    Self-closing/void inline tags (<br>, <img>, <wbr>) are self-balanced.
    """
    balanced = set()
    stack = []
    for idx, (kind, text) in enumerate(tokens):
        if kind != "tag" or not is_inline_tag(text):
            continue
        name = tag_name(text)
        if text.startswith("</"):
            for si in range(len(stack) - 1, -1, -1):
                if stack[si][0] == name:
                    _, open_idx = stack.pop(si)
                    if not is_ev_claim(tokens[open_idx][1]):
                        balanced.add(open_idx)
                        balanced.add(idx)
                    break
        elif text.rstrip().rstrip(">").endswith("/") or name in ("br", "wbr", "img"):
            balanced.add(idx)  # void/self-closing: needs no partner
        else:
            stack.append((name, idx))
    return balanced


def emit_run(tokens, wrapper):
    """Render a changed run.

    wrapper is 'ins' or 'del'. Structural tags — and inline tags whose partner
    falls outside this run — close/skip the wrapper so the result stays
    well-formed:
      * ins: such tags are emitted verbatim (outside the wrapper); words and
        balanced inline tags are highlighted inside <ins>.
      * del: a fully-deleted subtree's structural tags are dropped (open+close
        both fall in the deleted run, so nesting stays balanced); deleted words
        and balanced inline tags are shown struck-through inside <del>.
    """
    out = []
    open_wrap = False
    inline_ok = balanced_inline(tokens)

    def close():
        nonlocal open_wrap
        if open_wrap:
            out.append(f"</{wrapper}>")
            open_wrap = False

    def open_():
        nonlocal open_wrap
        if not open_wrap:
            out.append(f"<{wrapper}>")
            open_wrap = True

    for idx, (kind, text) in enumerate(tokens):
        highlightable = kind == "word" or (
            kind == "tag" and is_inline_tag(text) and idx in inline_ok
        )
        if kind == "tag" and not highlightable:
            close()
            pop = EV_POP_RE.match(text)
            if pop:
                # Stamp the op so the restore pass can chip the claim. A removed
                # popover is kept as a placeholder (it becomes a chip) rather
                # than being dropped with the rest of the deleted run.
                out.append(
                    EV_POP_OP_PLACEHOLDER
                    % (pop.group(1), "add" if wrapper == "ins" else "del")
                )
            elif wrapper == "ins":
                out.append(text)  # keep structure for inserted blocks
            # deleted structural / half-in inline tags are dropped with subtree
        elif kind == "space":
            out.append(text)  # rides along whether or not a wrapper is open
        else:  # word or balanced inline tag
            open_()
            out.append(text)
    close()
    return "".join(out)


# Evidence popovers (`<span class="ev-pop">…</span>`, injected by the workspace
# evidence extension) are hover-only payloads, not prose, and word-diffing them
# broke twice on real PRs: an inserted popover landed *inside* the `<ins>`
# wrapper, so it stopped being the direct child `.ev:hover > .ev-pop` needs and
# the hover showed nothing; and evidence added to otherwise-unchanged prose was
# marked only inside that hidden popover, i.e. invisibly. So each popover is
# swapped for one opaque placeholder tag before the diff and restored after.
EV_POP_OPEN_RE = re.compile(
    r"""(?is)<span(?=\s|/|>)[^>]*?\sclass\s*=\s*(?P<quote>["'])(?P<classes>.*?)(?P=quote)[^>]*>"""
)
# `wc-evpop` is deliberately not an inline tag: emit_run then treats it as
# structural and emits it OUTSIDE any <ins>, which is what restores the
# direct-child relationship the popover CSS depends on.
EV_POP_PLACEHOLDER = '<wc-evpop data-k="%s">'
EV_POP_OP_PLACEHOLDER = '<wc-evpop data-k="%s" data-op="%s">'
EV_POP_RE = re.compile(r'<wc-evpop data-k="([0-9a-f]+)"(?: data-op="(add|del)")?>')

EV_CHIP = {
    "add": '<span class="wc-ev-chip wc-ev-add">evidence added</span>',
    "del": '<span class="wc-ev-chip wc-ev-del">evidence removed</span>',
}


def _matching_close(content, start, name):
    """Index just past the `</name>` that closes the element open at `start`."""
    pat = re.compile(rf"(?is)<(/?){re.escape(name)}(?=\s|/|>)[^>]*>")
    depth, pos = 1, start
    while True:
        m = pat.search(content, pos)
        if not m:
            return None
        pos = m.end()
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return m.end()


def extract_ev_popovers(content):
    """Swap every evidence popover subtree for a placeholder; return both."""
    out, store, pos = [], {}, 0
    for m in EV_POP_OPEN_RE.finditer(content):
        if "ev-pop" not in m.group("classes").split():
            continue
        if m.start() < pos:
            continue
        end = _matching_close(content, m.end(), "span")
        if end is None:
            continue
        frag = content[m.start() : end]
        key = hashlib.sha1(frag.encode("utf-8")).hexdigest()[:16]
        store[key] = frag
        out.append(content[pos : m.start()])
        out.append(EV_POP_PLACEHOLDER % key)
        pos = end
    out.append(content[pos:])
    return "".join(out), store


def restore_ev_popovers(content, store):
    """Put the popovers back, chipping the ones this change added or removed."""

    def sub(m):
        key, op = m.group(1), m.group(2)
        chip = EV_CHIP.get(op, "")
        if op == "del":
            return chip  # the quote itself is gone; only the fact of it remains
        return chip + store.get(key, "")

    return EV_POP_RE.sub(sub, content)


def diff_content(old, new):
    """Inline word-level diff of two content-HTML strings."""
    old, old_pops = extract_ev_popovers(old)
    new, new_pops = extract_ev_popovers(new)
    a, b = tokenize(old), tokenize(new)
    # Align on the visible string of each token.
    ak = [t[1] for t in a]
    bk = [t[1] for t in b]
    # SequenceMatcher without autojunk is quadratic; a local edit to a large
    # page (a slide deck) only needs the span between the common ends.
    lo = 0
    while lo < min(len(ak), len(bk)) and ak[lo] == bk[lo]:
        lo += 1
    hi = 0
    while hi < min(len(ak), len(bk)) - lo and ak[-1 - hi] == bk[-1 - hi]:
        hi += 1
    a_middle, b_middle = ak[lo : len(ak) - hi], bk[lo : len(bk) - hi]
    # Distant edits can still leave a long, highly repetitive middle. Estimate
    # candidate token matches before allowing the expensive exact matcher; its
    # popular-token heuristic keeps those cases responsive, at the cost of
    # coarser highlighting inside that changed span.
    a_counts, b_counts = Counter(a_middle), Counter(b_middle)
    candidates = sum(count * b_counts[token] for token, count in a_counts.items())
    sm = difflib.SequenceMatcher(
        None, a_middle, b_middle, autojunk=candidates > 1_000_000
    )
    opcodes = [
        (op, i1 + lo, i2 + lo, j1 + lo, j2 + lo)
        for op, i1, i2, j1, j2 in sm.get_opcodes()
    ]
    if lo:
        opcodes.insert(0, ("equal", 0, lo, 0, lo))
    if hi:
        opcodes.append(("equal", len(ak) - hi, len(ak), len(bk) - hi, len(bk)))
    out = []
    changed = False
    for op, i1, i2, j1, j2 in opcodes:
        if op == "equal":
            out.append("".join(t[1] for t in a[i1:i2]))
        elif op == "insert":
            changed = True
            out.append(emit_run(b[j1:j2], "ins"))
        elif op == "delete":
            changed = True
            out.append(emit_run(a[i1:i2], "del"))
        elif op == "replace":
            changed = True
            out.append(emit_run(a[i1:i2], "del"))
            out.append(emit_run(b[j1:j2], "ins"))
    return restore_ev_popovers("".join(out), {**old_pops, **new_pops}), changed


# Chrome for the diff scaffolding (header, TOC, per-page section banners) and
# the added/removed highlighting. This is layered *after* the site theme when
# one is available, so it only styles our own wrapper classes and the
# <ins>/<del> runs — the page content keeps the site's real typography, colors,
# code highlighting, and dark/light palette.
#
# Highlight colors are the GitHub-diff palette: a green background for added
# text and a red background + strikethrough for removed text — the same channels
# GitHub uses for word-level diffs. We deliberately do NOT underline insertions:
# in an additive document (a growing survey) almost every run is an insertion, so
# underlining them all paints the page with lines and drowns out any other
# underline cue — including an evidence claim's own dotted underline. Removed
# text keeps its strikethrough (a sparse, meaningful cue that also gives
# color-blind reviewers a non-color signal on the del side). Insertions use a
# slim leading edge instead of an underline, so they remain identifiable without
# recreating the field of horizontal lines that obscured evidence claims.
DIFF_STYLE = """
.wc-scope { --wc-ins-bg: #d7f5dd; --wc-ins-line: #1a7f37; --wc-ins-fg: #032b13;
            --wc-del-bg: #ffd7d5; --wc-del-line: #cf222e; --wc-del-fg: #40100c;
            --wc-muted: #57606a; --wc-changed: #0969da; --wc-new: #1a7f37;
            --wc-removed: #cf222e; --wc-tag-fg: #fff; --wc-border: #d0d7de; }
/* Follow the mode the site is shown in (`data-wc-mode`, set by MODE_JS) when a
   theme is reused. The media query is only for standalone output. */
[data-wc-mode="dark"] .wc-scope { --wc-ins-bg: #12341f; --wc-ins-line: #3fb950; --wc-ins-fg: #d7ffe4;
                    --wc-del-bg: #4a1512; --wc-del-line: #f85149; --wc-del-fg: #ffdcd7;
                    --wc-muted: #8b949e; --wc-changed: #58a6ff; --wc-new: #3fb950;
                    --wc-removed: #f85149; --wc-tag-fg: #0d1117; --wc-border: #30363d; }
@media (prefers-color-scheme: dark) {
  .wc-scope.wc-standalone {
              --wc-ins-bg: #12341f; --wc-ins-line: #3fb950; --wc-ins-fg: #d7ffe4;
              --wc-del-bg: #4a1512; --wc-del-line: #f85149; --wc-del-fg: #ffdcd7;
              --wc-muted: #8b949e; --wc-changed: #58a6ff; --wc-new: #3fb950;
              --wc-removed: #f85149; --wc-tag-fg: #0d1117; --wc-border: #30363d; }
}
.wc-scope header.diff-head { padding: 1.25rem 0 0.5rem; margin-bottom: 1rem;
    border-bottom: 1px solid var(--wc-border); }
.wc-scope header.diff-head h1 { margin: 0 0 .25rem; }
.wc-scope header.diff-head p, .wc-scope .legend, .wc-scope .empty {
    color: var(--wc-muted); }
.wc-scope .legend { font-size: .9rem; }
.wc-scope .legend ins, .wc-scope .legend del { padding: 0 .25em; }
.wc-scope .empty { font-style: italic; }
.wc-scope .wc-note { margin: .25rem 0 .5rem; }
.wc-scope .wc-preview { color: var(--wc-muted); font-size: .95rem;
    padding: .5rem .85rem; border-left: 3px solid var(--wc-border);
    white-space: pre-wrap; overflow-wrap: break-word; }
/* The paper's own viewer, as on its page: one bar over the PDF, a page tall
   at the column's width (whatever the window), and ⤢ for the whole window. */
.wc-scope .paper-view { margin-top: .5rem; }
.wc-scope .paper-bar { display: flex; flex-wrap: wrap; align-items: center;
    gap: .25rem .9rem; font-size: .9rem; padding: .35rem 0;
    border-bottom: 1px solid var(--wc-border); }
.wc-scope .paper-title { font-size: 1rem; }
.wc-scope .paper-expand, .wc-scope .paper-modes button { font: inherit; line-height: 1.2;
    padding: .2rem .55rem; border: 1px solid var(--wc-border); border-radius: 6px;
    background: transparent; color: inherit; cursor: pointer; }
.wc-scope .paper-modes { display: inline-flex; gap: .3rem; margin-left: auto; }
.wc-scope .paper-modes button { font-size: .85rem; padding: .15rem .7rem; }
.wc-scope .paper-modes button[aria-pressed="true"] { font-weight: 600;
    background: var(--bs-body-color, #24292f); color: var(--bs-body-bg, #fff);
    border-color: var(--bs-body-color, #24292f); }
.wc-scope .paper-view object { display: block; width: 100%; aspect-ratio: 3 / 4; border: 0; }
.wc-scope .paper-view.paper-full { position: fixed; inset: 0; z-index: 1050; margin: 0;
    display: flex; flex-direction: column; background: var(--bs-body-bg, #fff); }
.wc-scope .paper-full .paper-bar { padding: .35rem .75rem; }
.wc-scope .paper-full object { flex: 1; aspect-ratio: auto; }
.wc-scope nav.toc { font-size: .95rem; margin: 0 0 2rem; padding: .75rem 1rem;
    border: 1px solid var(--wc-border); border-radius: 6px; }
.wc-scope nav.toc a { display: inline-block; margin-right: 1rem; }
.wc-scope section.page-diff { margin-top: 2.5rem; padding: .75rem 1rem 1rem;
    border: 1px solid var(--wc-border); border-left: 4px solid var(--wc-changed);
    border-radius: 6px; }
.wc-scope section.page-diff.new { border-left-color: var(--wc-new); }
.wc-scope section.page-diff.removed { border-left-color: var(--wc-removed); }
.wc-scope section.page-diff > h2 { margin-top: .25rem; }
.wc-scope .tag { font-weight: 600;
    padding: .15em .6em; border-radius: 1em; vertical-align: middle;
    margin-left: .5em; color: var(--wc-tag-fg); }
.wc-scope section.page-diff > h2 .tag { font-size: .65em; }
.wc-scope nav.toc .tag { font-size: .75em; }
.wc-scope .tag.changed { background: var(--wc-changed); color: var(--wc-tag-fg); }
.wc-scope .tag.new { background: var(--wc-new); color: var(--wc-tag-fg); }
.wc-scope .tag.removed { background: var(--wc-removed); color: var(--wc-tag-fg); }
.wc-scope .diff-body { overflow-wrap: break-word; }
.wc-scope ins { background: var(--wc-ins-bg); color: var(--wc-ins-fg);
    text-decoration: none; border-inline-start: 2px solid var(--wc-ins-line);
    border-radius: 2px; padding: 0 .1em; }
.wc-scope del { background: var(--wc-del-bg); color: var(--wc-del-fg);
    text-decoration: line-through; text-decoration-color: var(--wc-del-line);
    text-decoration-thickness: 2px; border-radius: 2px; padding: 0 .1em; }
/* Links: no resting underline on the diff (GitHub's diff view does the same).
   The reused theme carries Bootstrap's default `a { text-decoration: underline }`,
   which otherwise underlines every citation, crossref (e.g. "Table 1") and bare
   URL in the change — and inside an inserted run those links pick up the green
   ins colour, reading as green underlines scattered across the page. A modest
   weight change keeps a persistent non-colour cue without adding another field
   of lines; the underline returns on hover or keyboard focus. */
.wc-scope a { text-decoration: none; font-weight: 600; }
.wc-scope a:hover, .wc-scope a:focus { text-decoration: underline; }
/* Evidence claims (`.ev`) need a visible cue on the diff. The extension's
   default thin currentColor border is intentionally subtle on a normal
   report, but becomes effectively invisible against the green insertion tint.
   Strengthen it to a 2px dotted rule in the active theme's link color, so it
   stays an underline rather than another background and follows light/dark. */
.wc-scope .wc-ev-chip { font-size: .7em; font-weight: 600; white-space: nowrap; }
.wc-scope .wc-ev-chip.wc-ev-add { background: var(--wc-new); }
.wc-scope .wc-ev-chip.wc-ev-del { background: var(--wc-removed); }
.wc-scope .ev { border-bottom: 2px dotted var(--bs-link-color, var(--wc-changed)); }
/* Insertions are background-only: the `ins` rule above sets
   `text-decoration: none` to suppress the browser UA-default `ins {
   text-decoration: underline }` (otherwise every added run keeps a green
   underline even with no explicit underline rule in this stylesheet). */
.wc-scope ins img, .wc-scope del img { outline: 3px solid; }
.wc-scope ins img { outline-color: var(--wc-ins-line); }
.wc-scope del img { outline-color: var(--wc-del-line); opacity: .6; }
/* GitHub-style collapsed hunks: runs of unchanged blocks are folded client-side
   into disclosure widgets so a reviewer lands on the changes, not context. */
.wc-scope .wc-toolbar { margin: -.5rem 0 1.5rem; }
.wc-scope .wc-toolbar button { font: inherit; font-size: .85rem; cursor: pointer;
    color: var(--wc-changed); background: transparent; padding: .35em .9em;
    border: 1px solid var(--wc-border); border-radius: 6px; }
.wc-scope .wc-toolbar button:hover { border-color: var(--wc-changed); }
/* Same expander bar as a deck's folded slides (deck-review.py .wc-expander). */
.wc-scope details.wc-fold { margin: .85rem 0; }
.wc-scope details.wc-fold > summary { cursor: pointer; list-style: none;
    display: flex; align-items: baseline; gap: .55em; padding: 4px 12px;
    color: inherit; font-size: .9rem; user-select: none;
    background: rgba(84,174,255,.12); border: 1px solid rgba(84,174,255,.35);
    border-radius: 6px; }
.wc-scope details.wc-fold > summary::-webkit-details-marker { display: none; }
.wc-scope details.wc-fold > summary::before { content: "\\2195"; }
.wc-scope details.wc-fold > summary:hover { background: rgba(84,174,255,.25); }
.wc-scope details.wc-fold[open] > summary { margin-bottom: 8px; }
.wc-scope .wc-fold-body { padding: .25rem 1rem .35rem; }
"""

# Client-side progressive enhancement: fold runs of unchanged block elements
# (recursively, at every nesting level) into collapsible <details>, keeping a
# block of context next to each change — the GitHub "hidden unchanged lines"
# affordance. It runs on the already-parsed DOM and only *moves* balanced element
# nodes, so it cannot corrupt markup; with JS disabled the full content is shown.
FOLD_JS = r"""
(function () {
  "use strict";
  var MIN_CHARS = 260;   // don't bother folding a small gap
  var MIN_BLOCKS = 1;    // a rendered block can contain an entire long section
  var CONTEXT = 1;       // unchanged blocks kept visible beside a change
  var MAX_CONTEXT_CHARS = 500; // fold large neighbors instead of treating them as context

  // Be conservative about where we insert the block-level disclosure wrapper.
  // A denylist is unsafe here: besides tables/lists, phrasing-only containers
  // such as paragraphs, headings, and summaries cannot contain one. Unknown
  // containers are therefore traversal-only. This allowlist covers the ordinary
  // flow-content containers emitted by Quarto in which a disclosure is valid.
  var FOLD_CONTAINERS = { BODY: 1, DIV: 1, MAIN: 1, ARTICLE: 1, SECTION: 1,
    NAV: 1, ASIDE: 1, HEADER: 1, FOOTER: 1, BLOCKQUOTE: 1, FIGURE: 1,
    FIGCAPTION: 1, LI: 1, DD: 1, TD: 1, TH: 1 };

  // Out-of-flow or hidden subtrees — an absolutely-positioned hover popover /
  // tooltip, a display:none or visibility:hidden aside — are not part of the
  // readable diff flow. Folding their "unchanged" inner blocks is pointless and
  // corrupting: e.g. an inline hover-popover attached to a claim would have its
  // quote collapsed behind a fold that only appears once the reader hovers. Skip
  // such subtrees entirely (don't recurse into them, never fold them).
  function inFlow(el) {
    var view = el.ownerDocument.defaultView;
    var s = view && view.getComputedStyle ? view.getComputedStyle(el) : null;
    if (!s) return true;
    if (s.display === "none" || s.visibility === "hidden") return false;
    if (s.position === "absolute" || s.position === "fixed") return false;
    return true;
  }
  function hasChange(el) {
    return el.tagName === "INS" || el.tagName === "DEL" ||
           !!el.querySelector("ins, del");
  }
  function words(str) { var m = str.trim().match(/\S+/g); return m ? m.length : 0; }
  function headingText(el) {
    if (/^H[1-6]$/.test(el.tagName)) return el.textContent.trim();
    var h = el.querySelector("h1, h2, h3, h4, h5, h6");
    return h ? h.textContent.trim() : "";
  }
  function summaryText(run) {
    var titles = [], w = 0;
    run.forEach(function (el) {
      var t = headingText(el);
      if (t) titles.push(t.length > 60 ? t.slice(0, 57) + "…" : t);
      w += words(el.textContent);
    });
    var n = run.length;
    var label = n + " unchanged " + (n === 1 ? "block" : "blocks");
    if (titles.length) {
      var shown = titles.slice(0, 3).join(", ");
      if (titles.length > 3) shown += ", …";
      label += ": " + shown;
    }
    return label + " · " + w + " words hidden";
  }
  function collapse(container, run) {
    var d = document.createElement("details");
    d.className = "wc-fold wc-expander";
    var s = document.createElement("summary");
    s.textContent = "Expand " + summaryText(run);
    var wrap = document.createElement("div");
    wrap.className = "wc-fold-body";
    container.insertBefore(d, run[0]);
    d.appendChild(s);
    run.forEach(function (el) { wrap.appendChild(el); });
    d.appendChild(wrap);
  }
  function fold(container) {
    var kids = Array.prototype.slice.call(container.children);
    if (!kids.length) return;
    var changed = kids.map(hasChange);
    var flow = kids.map(inFlow);
    var keep = kids.map(function () { return false; });
    kids.forEach(function (el, k) {
      if (!changed[k]) return;
      for (var j = Math.max(0, k - CONTEXT);
           j <= Math.min(kids.length - 1, k + CONTEXT); j++) {
        // Rendered blocks are not source lines: a single sibling can contain a
        // whole section. Keep compact neighbors as context, but fold large ones.
        keep[j] = changed[j] || kids[j].textContent.length <= MAX_CONTEXT_CHARS;
      }
    });
    // Out-of-flow/hidden children are never folded and act as run boundaries.
    // (After the context pass so it can't be undone by a neighbor's window.)
    kids.forEach(function (el, k) { if (!flow[k]) keep[k] = true; });
    // Recurse into changed, in-flow containers before moving sibling runs — but
    // never into an <ins>/<del> wrapper. Those wrap a run of inserted/deleted
    // inline content, inside which nothing is "unchanged"; recursing there makes
    // hasChange() see every child as unchanged (no ins/del *descendant*) and fold
    // real inserted text — e.g. collapsing a claim's hover-popover quote behind a
    // bogus "N unchanged blocks" toggle.
    kids.forEach(function (el, k) {
      if (changed[k] && flow[k] && el.children.length &&
          el.tagName !== "INS" && el.tagName !== "DEL") fold(el);
    });
    // Only collapse sibling runs where a block-level disclosure is a valid
    // child. Still recurse through other containers so a changed table cell or
    // list item can fold its own flow-content children.
    if (!FOLD_CONTAINERS[container.tagName]) return;
    var start = 0;
    while (start < kids.length) {
      if (keep[start]) { start++; continue; }
      var end = start;
      while (end < kids.length && !keep[end]) end++;
      var run = kids.slice(start, end);
      var chars = run.reduce(function (a, el) { return a + el.textContent.length; }, 0);
      if (run.length >= MIN_BLOCKS && chars >= MIN_CHARS) collapse(container, run);
      start = end;
    }
  }
  function addToolbar() {
    if (!document.querySelector("details.wc-fold")) return;
    var anchor = document.querySelector("section.page-diff");
    if (!anchor) return;
    var bar = document.createElement("div");
    bar.className = "wc-toolbar";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Expand all unchanged";
    btn.addEventListener("click", function () {
      var open = btn.getAttribute("data-open") === "1";
      document.querySelectorAll("details.wc-fold").forEach(function (d) {
        d.open = !open;
      });
      btn.setAttribute("data-open", open ? "0" : "1");
      btn.textContent = open ? "Expand all unchanged" : "Collapse all unchanged";
    });
    bar.appendChild(btn);
    anchor.parentNode.insertBefore(bar, anchor);
  }
  function run() {
    document.querySelectorAll("section.page-diff.changed .diff-body")
      .forEach(fold);
    addToolbar();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else { run(); }
})();
"""
