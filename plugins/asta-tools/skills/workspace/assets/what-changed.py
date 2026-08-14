#!/usr/bin/env python3
"""Generate a "What changed" page for a Quarto site preview.

Given two rendered site trees — a baseline (what's live on the site's gh-pages
root, i.e. `main`) and a candidate (this PR's freshly rendered `_site/`) — emit
a single self-contained HTML page that shows, per document, the rendered content
with inline additions/removals highlighted. Reviewers get one link that lands
them on exactly what changed, instead of the site root to hunt through.

Design notes:
  * Compares the rendered `<main>` content of each page, not the source `.qmd`,
    so reviewers see the change the way readers will.
  * Quarto's `date-modified: last-modified` stamps a fresh "Modified" date into
    every page on every render; that is normalized away so a page only shows up
    when its actual content changed.
  * Inline diffing keeps the HTML valid: `<ins>`/`<del>` only ever wrap runs of
    words and inline formatting tags. Block/structural tags are emitted outside
    the wrapper (insertions) or dropped with their fully-deleted subtree
    (deletions), so list/table/section nesting is never corrupted.
  * Long stretches of unchanged content are folded into GitHub-style "N
    unchanged blocks" toggles, so a reviewer lands on the changes instead of a
    wall of context. Folding is progressive enhancement done client-side on the
    already-parsed DOM (it only moves balanced element nodes, so it cannot break
    markup); with JS off, the full rendered diff is shown.
  * The diff page never embeds or executes a source page's own <script>/<style>.
    Those are stripped from every embedded body. Executing foreign page markup
    is both wrong (the page's nav/widget JS expects DOM we don't reproduce) and
    actively harmful when a PR touches several such pages: two self-contained
    reports embedded in one document collide on duplicate element ids and
    duplicate top-level JS identifiers, so the second one throws and renders
    blank — the exact failure this generator exists to avoid.
  * Word-level inline diffing is scoped to *prose* pages. A page whose visible
    content is produced by client-side script — Plotly/Bokeh/Vega widgets,
    Observable cells, notebook cell outputs, or a bespoke data-driven report
    (an empty container filled by a large inline data payload) — cannot be shown
    by embedding its stripped body (that leaves an empty shell) and re-renders to
    volatile markup a word diff would light up as spurious change. Such pages are
    represented by a compact summary card (state + title + a static-text preview)
    that links to the full rendered page, for every state (new/removed/changed),
    rather than embedded inline.

Pure standard library so it runs anywhere Quarto CI already runs (no pip step).
"""

import argparse
import difflib
import html
import os
import re
import sys

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


def extract_main(doc):
    """Return the inner HTML of the page's main content region."""
    m = re.search(r"(?is)<main\b[^>]*>(.*?)</main>", doc)
    if m:
        return m.group(1)
    m = re.search(r"(?is)<body\b[^>]*>(.*?)</body>", doc)
    return m.group(1) if m else doc


def normalize(content):
    """Strip volatile bits so only real content changes register.

    Quarto re-stamps the last-modified date on every render; if we diffed it,
    every page would look changed. Remove the title-block meta date region.
    """
    # Quarto title-block "Modified" date lives in a quarto-title-meta block.
    content = re.sub(
        r'(?is)<div class="quarto-title-meta-heading">\s*Modified\s*</div>\s*'
        r'<div class="quarto-title-meta-contents">.*?</div>',
        "",
        content,
    )
    # Bare date-modified paragraph, if the theme renders one.
    content = re.sub(r'(?is)<p class="date-modified">.*?</p>', "", content)
    return content


# Markers that a rendered page carries *computed* output — Plotly/Bokeh/Vega/
# leaflet widgets, Observable/OJS cells, Jupyter widget mounts, or notebook cell
# outputs. Such output re-renders to volatile markup (regenerated DOM ids,
# reordered JSON payloads, reformatted floats), so a word-level HTML diff of it
# is noise; those pages are shown whole instead of inline-diffed.
COMPUTED_MARKERS = re.compile(
    r"(?is)"
    r"class\s*=\s*[\"'][^\"']*\b(?:"
    r"cell-output|cell-output-display|plotly-graph-div|js-plotly-plot|bk-root|"
    r"observablehq|ojs-in-a-box|jupyter-widgets|widget-subarea|leaflet-container|"
    r"vega-embed|vega-vis|dygraph|htmlwidget"
    r")\b"
    r"|<script\b[^>]*\btype\s*=\s*[\"']application/(?:json|vnd\.[^\"']+)[\"']"
    r"|\brequire\(\s*\[\s*[\"']plotly"
)


def has_computed_output(content):
    """True when the rendered content embeds executable/computed output."""
    return bool(COMPUTED_MARKERS.search(content))


SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1>")


def strip_volatile(content):
    """Drop <script>/<style> subtrees so an embedded body carries no executable
    code or foreign styling.

    The diff page ships its own single script (folding) and its own styles; a
    source page's scripts must never run here — they collide with each other and
    with ours (duplicate element ids, re-declared top-level identifiers) and only
    bloat the output (a data-driven report's payload can be multiple MB).
    """
    return SCRIPT_STYLE_RE.sub("", content)


def is_script_heavy(content):
    """True when inline <script> is the bulk of a page.

    Catches bespoke client-rendered pages that carry no framework marker
    `has_computed_output` would recognise — e.g. a self-contained report that is
    an empty container plus one large inline data payload the script expands on
    load. A prose page's content region carries essentially no script, so the
    ratio cleanly separates the two.
    """
    script_bytes = sum(len(m.group(0)) for m in SCRIPT_STYLE_RE.finditer(content))
    return script_bytes >= 20_000 and script_bytes >= 0.5 * max(len(content), 1)


def is_self_contained(content):
    """True when a page's visible content depends on running its own scripts.

    Such a page can't be faithfully embedded in the diff (stripping its scripts
    leaves an empty shell; keeping them collides with every other embedded page),
    so it is shown as a summary card that links to the full rendered page.
    """
    return has_computed_output(content) or is_script_heavy(content)


def summary_card(main_content, link, note):
    """Compact stand-in for a self-contained page: a note (with a link to the
    full page when one exists) plus a short static-text preview of whatever the
    page renders without scripts, so the reviewer knows what the page is."""
    if link:
        head = (
            f'<p class="wc-note">{html.escape(note)} — '
            f'<a href="{html.escape(link)}">open the full page</a> to view it.</p>'
        )
    else:
        head = f'<p class="wc-note">{html.escape(note)}.</p>'
    text = visible_text(main_content)
    if not text:
        return head
    snippet = text[:600]
    if len(text) > 600:
        snippet = snippet.rsplit(" ", 1)[0] + " …"
    return head + f'<p class="wc-preview">{html.escape(snippet)}</p>'


def visible_text(content):
    """Plain visible text of a content fragment.

    Drops <script>/<style> subtrees and every tag, unescapes entities, and
    collapses whitespace. Used to decide whether a computed page *really*
    changed, ignoring the volatile widget markup and script payloads that a
    re-render regenerates even when the source is untouched.
    """
    text = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", " ", content)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


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
            if wrapper == "ins":
                out.append(text)  # keep structure for inserted blocks
            # deleted structural / half-in inline tags are dropped with subtree
        elif kind == "space":
            out.append(text)  # rides along whether or not a wrapper is open
        else:  # word or balanced inline tag
            open_()
            out.append(text)
    close()
    return "".join(out)


def diff_content(old, new):
    """Inline word-level diff of two content-HTML strings."""
    a, b = tokenize(old), tokenize(new)
    # Align on the visible string of each token.
    ak = [t[1] for t in a]
    bk = [t[1] for t in b]
    sm = difflib.SequenceMatcher(None, ak, bk, autojunk=False)
    out = []
    changed = False
    for op, i1, i2, j1, j2 in sm.get_opcodes():
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
    return "".join(out), changed


def list_pages(root):
    pages = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not f.endswith(".html"):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root)
            pages[rel] = full
    return pages


# Chrome for the diff scaffolding (header, TOC, per-page section banners) and
# the added/removed highlighting. This is layered *after* the site theme when
# one is available, so it only styles our own wrapper classes and the
# <ins>/<del> runs — the page content keeps the site's real typography, colors,
# code highlighting, and dark/light palette.
#
# Highlight colors are the GitHub-diff palette: high enough contrast to read the
# text on top and to distinguish added from removed at a glance, and never
# color-only (added is underlined, removed is struck through) so the diff is
# legible to color-blind reviewers too.
DIFF_STYLE = """
.wc-scope { --wc-ins-bg: #d7f5dd; --wc-ins-line: #1a7f37; --wc-ins-fg: #032b13;
            --wc-del-bg: #ffd7d5; --wc-del-line: #cf222e; --wc-del-fg: #40100c;
            --wc-muted: #57606a; --wc-changed: #0969da; --wc-new: #1a7f37;
            --wc-removed: #cf222e; --wc-tag-fg: #fff; --wc-border: #d0d7de; }
/* Follow Quarto's rendered theme mode when a theme is reused. The media-query
   fallback is only for standalone output, where no Quarto mode is available. */
.wc-scope.wc-dark { --wc-ins-bg: #12341f; --wc-ins-line: #3fb950; --wc-ins-fg: #d7ffe4;
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
    text-decoration: underline; text-decoration-color: var(--wc-ins-line);
    text-decoration-thickness: 2px; border-radius: 2px; padding: 0 .1em; }
.wc-scope del { background: var(--wc-del-bg); color: var(--wc-del-fg);
    text-decoration: line-through; text-decoration-color: var(--wc-del-line);
    text-decoration-thickness: 2px; border-radius: 2px; padding: 0 .1em; }
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
.wc-scope details.wc-fold { margin: .85rem 0; border: 1px dashed var(--wc-border);
    border-radius: 6px; }
.wc-scope details.wc-fold > summary { cursor: pointer; list-style: none;
    display: flex; align-items: baseline; gap: .55em; padding: .5em .85em;
    color: var(--wc-muted); font-size: .85rem; user-select: none; }
.wc-scope details.wc-fold > summary::-webkit-details-marker { display: none; }
.wc-scope details.wc-fold > summary::before { content: "\\25B8"; }
.wc-scope details.wc-fold[open] > summary::before { content: "\\25BE"; }
.wc-scope details.wc-fold > summary:hover { color: var(--wc-changed); }
.wc-scope details.wc-fold[open] > summary { border-bottom: 1px dashed var(--wc-border); }
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
    d.className = "wc-fold";
    var s = document.createElement("summary");
    s.textContent = summaryText(run);
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
    // Recurse into changed containers before moving sibling runs.
    kids.forEach(function (el, k) {
      if (changed[k] && el.children.length) fold(el);
    });
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

# Body typography for the fallback path, when no site theme could be reused.
STANDALONE_STYLE = """
:root { color-scheme: light dark; }
body { font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
       Helvetica, Arial, sans-serif; margin: 0; padding: 0 1.5rem 4rem;
       max-width: 60rem; margin-inline: auto; color: #1b1b1b; }
.wc-scope section.page-diff table { border-collapse: collapse; }
.wc-scope section.page-diff td, .wc-scope section.page-diff th {
    border: 1px solid var(--wc-border); padding: .3em .5em; }
@media (prefers-color-scheme: dark) { body { background: #0d1117; color: #e6edf3; } }
"""


def extract_theme_css(doc, depth):
    """Pull the site theme's stylesheets out of a rendered page's <head>.

    We reuse only <link rel="stylesheet"> and inline <style> — never the theme's
    scripts — so the diff content renders with the real site typography, colors,
    and code highlighting, without dragging in navbar/toggle JS that expects DOM
    we don't reproduce. Relative asset URLs are rebased from the template page's
    depth up to the preview root, where what-changed.html lives.
    """
    head_m = re.search(r"(?is)<head\b[^>]*>(.*?)</head>", doc)
    if not head_m:
        return None
    head = head_m.group(1)
    parts = []
    for m in re.finditer(r"(?is)<link\b[^>]*>", head):
        tag = m.group(0)
        if re.search(r'rel\s*=\s*["\']?[^"\'>]*stylesheet', tag, re.I):
            parts.append(rebase_urls(tag, depth))
    for m in re.finditer(r"(?is)<style\b[^>]*>.*?</style>", head):
        parts.append(rebase_urls(m.group(0), depth))
    return "\n".join(parts) if parts else None


def extract_theme_mode(doc):
    """Return Quarto's compiled Bootstrap mode (light or dark), if present."""
    bootstrap = re.search(
        r'(?is)<link\b(?=[^>]*\bid\s*=\s*["\']quarto-bootstrap["\'])[^>]*>', doc
    )
    if not bootstrap:
        return None
    mode = re.search(
        r'\bdata-mode\s*=\s*["\'](light|dark)["\']', bootstrap.group(0), re.I
    )
    return mode.group(1).lower() if mode else None


def rebase_urls(text, depth):
    """Strip `depth` leading `../` from href/src/url() so root-relative links
    resolve from the preview root instead of the template page's subdirectory."""
    if depth <= 0:
        return text
    prefix = "../" * depth

    def fix(m):
        attr, quote, url = m.group(1), m.group(2), m.group(3)
        if url.startswith(prefix):
            url = url[len(prefix) :]
        return f"{attr}={quote}{url}{quote}"

    text = re.sub(r'(href|src)\s*=\s*(["\'])([^"\']*)\2', fix, text, flags=re.I)
    return text


def page_title(doc, rel):
    m = re.search(r"(?is)<title>(.*?)</title>", doc)
    if m:
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        if t:
            return t
    return rel


def anchor_id(rel):
    return "p-" + re.sub(r"[^a-zA-Z0-9]+", "-", rel).strip("-")


def pick_template(new_pages):
    """Choose the shallowest rendered page to borrow the site theme from.

    A root-level page (e.g. index.html) keeps asset URLs simplest to rebase.
    Returns (doc_html, depth) or (None, 0) if nothing suitable exists.
    """
    if not new_pages:
        return None, 0
    rel = min(new_pages, key=lambda r: (r.replace(os.sep, "/").count("/"), r))
    depth = rel.replace(os.sep, "/").count("/")
    try:
        return open(new_pages[rel], encoding="utf-8").read(), depth
    except OSError:
        return None, 0


def build(old_root, new_root, preview_url, title):
    old_pages = list_pages(old_root)
    new_pages = list_pages(new_root)
    sections = []
    toc = []
    for rel in sorted(set(old_pages) | set(new_pages)):
        new_doc = (
            open(new_pages[rel], encoding="utf-8").read() if rel in new_pages else None
        )
        old_doc = (
            open(old_pages[rel], encoding="utf-8").read() if rel in old_pages else None
        )
        # The generated page lives inside the preview dir, so a bare relative
        # path deep-links to a sibling page without needing the absolute base.
        link = (preview_url.rstrip("/") + "/" + rel) if preview_url else rel
        if new_doc is not None and old_doc is not None:
            old_c = normalize(extract_main(old_doc))
            new_c = normalize(extract_main(new_doc))
            if is_self_contained(old_c) or is_self_contained(new_c):
                # Self-contained/computed page: its visible content is produced
                # by its own scripts, so an inline word diff is meaningless and
                # embedding it would run foreign markup here. Compare only the
                # stable visible text; if that changed, link it with a card.
                if visible_text(old_c) == visible_text(new_c):
                    continue  # only volatile rendering differs
                state = "changed"
                label = "changed · interactive page (linked)"
                body = summary_card(
                    new_c,
                    link,
                    "This page renders its content with client-side scripts",
                )
                title_txt = page_title(new_doc, rel)
            else:
                if (
                    re.sub(r"\s+", " ", old_c).strip()
                    == re.sub(r"\s+", " ", new_c).strip()
                ):
                    continue  # unchanged
                body, changed = diff_content(
                    strip_volatile(old_c), strip_volatile(new_c)
                )
                if not changed:
                    continue
                state, label = "changed", "changed"
                title_txt = page_title(new_doc, rel)
        elif new_doc is not None:
            new_c = normalize(extract_main(new_doc))
            title_txt = page_title(new_doc, rel)
            if is_self_contained(new_c):
                state, label = "new", "new page · interactive (linked)"
                body = summary_card(
                    new_c,
                    link,
                    "New page; renders its content with client-side scripts",
                )
            else:
                state, label = "new", "new page"
                body = strip_volatile(new_c)
        else:
            old_c = normalize(extract_main(old_doc))
            title_txt = page_title(old_doc, rel)
            if is_self_contained(old_c):
                state, label = "removed", "removed · interactive page"
                body = summary_card(
                    old_c,
                    "",
                    "Removed page; had rendered its content with client-side scripts",
                )
            else:
                state, label = "removed", "removed"
                body = strip_volatile(old_c)
        aid = anchor_id(rel)
        h2 = html.escape(title_txt)
        if state != "removed":
            h2 = f'<a href="{html.escape(link)}">{h2}</a>'
        state_class = "new" if state == "new" else state
        sections.append(
            f'<section class="page-diff {state}" id="{aid}">\n'
            f'<h2>{h2} <span class="tag {state_class}">{label}</span></h2>\n'
            f'<p class="legend"><code>{html.escape(rel)}</code></p>\n'
            f'<div class="diff-body">{body}</div>\n</section>'
        )
        toc.append(
            f'<a href="#{aid}">{html.escape(title_txt)} '
            f'<span class="tag {state_class}">{label}</span></a>'
        )

    if sections:
        n = len(sections)
        summary = f"{n} page{'s' if n != 1 else ''} changed"
        toc_html = f'<nav class="toc">{"".join(toc)}</nav>'
        body_html = "\n".join(sections)
    else:
        summary = "No rendered content changed"
        toc_html = ""
        body_html = (
            '<p class="empty">This PR changes no rendered page content '
            "relative to the deployed site. (It may still change source "
            "files, config, or metadata.)</p>"
        )

    legend = (
        '<p class="legend">Legend: <ins>added</ins> &middot; '
        "<del>removed</del>. Page titles link to the full preview.</p>"
    )
    escaped_title = html.escape(title)

    template_doc, depth = pick_template(new_pages)
    theme_css = extract_theme_css(template_doc, depth) if template_doc else None

    inner = (
        '<header class="diff-head"><h1>What changed</h1>'
        f"<p>{escaped_title} &middot; {summary}</p>{legend}</header>{toc_html}\n"
        f"{body_html}"
    )

    if theme_css:
        # Reuse the site theme, then wrap our content in Quarto's article
        # container so it inherits the real content width and typography.
        head = f"{theme_css}\n<style>{DIFF_STYLE}</style>"
        scope_class = (
            "wc-scope wc-dark"
            if extract_theme_mode(template_doc) == "dark"
            else "wc-scope"
        )
        body = (
            '<div class="page-columns page-rows-contents page-layout-article '
            f'{scope_class}">\n'
            '<main class="content" id="quarto-document-content">\n'
            f"{inner}\n</main>\n</div>"
        )
    else:
        head = f"<style>{STANDALONE_STYLE}{DIFF_STYLE}</style>"
        body = f'<div class="wc-scope wc-standalone">{inner}</div>'

    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>What changed &middot; {escaped_title}</title>"
        f"{head}</head><body>{body}<script>{FOLD_JS}</script></body></html>"
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--old", required=True, help="baseline rendered site root (deployed main)"
    )
    ap.add_argument(
        "--new", required=True, help="candidate rendered site root (this PR's _site)"
    )
    ap.add_argument("--out", required=True, help="output HTML path")
    ap.add_argument(
        "--preview-url", default="", help="base URL of the PR preview (for deep links)"
    )
    ap.add_argument(
        "--title", default="PR preview diff", help="site/PR label for the header"
    )
    args = ap.parse_args(argv)
    doc = build(args.old, args.new, args.preview_url, args.title)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"wrote {args.out} ({len(doc)} bytes)", file=sys.stderr)


if __name__ == "__main__":
    main()
