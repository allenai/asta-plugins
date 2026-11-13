#!/usr/bin/env python3
"""Generate a "What changed" page for a Quarto and paper preview.

Given two rendered site trees — a baseline (what's live on the site's gh-pages
root, i.e. `main`) and a candidate (this PR's freshly rendered `_site/`) — emit
a single self-contained HTML page that shows, per document, the rendered content
with inline additions/removals highlighted. A changed LaTeX paper is linked as a
diff PDF above the Quarto sections. Reviewers get one link that lands them on
the changes instead of the site root to hunt through.

Design notes:
  * Compares the rendered `<main>` content of each page, not the source `.qmd`,
    so reviewers see the change the way readers will.
  * Quarto's `date-modified: last-modified` stamps a fresh "Modified" date into
    every page on every render; that is normalized away so a page only shows up
    when its actual content changed.
  * The diff itself (align blocks, then mark words) is diff-engine.py; its
    header says what each kind of content is compared as and how it is drawn.
    A source page that only needs the diff can load that file alone.
  * Inline diffing keeps the HTML valid: `<ins>`/`<del>` only ever wrap runs of
    words and inline formatting tags. Block/structural tags are emitted outside
    the wrapper (insertions) or kept whole on a removed block, so
    list/table/section nesting is never corrupted.
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
import importlib.util
import json
import os
import re
import shutil
import sys
from collections import Counter
from collections.abc import Callable
from html.parser import HTMLParser
from typing import NamedTuple
from urllib.parse import quote, urlsplit


def _load_diff_engine():
    """diff-engine.py beside this script (the diff itself lives there)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diff-engine.py")
    spec = importlib.util.spec_from_file_location("diff_engine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_engine = _load_diff_engine()
(
    DIFF_STYLE,
    FOLD_JS,
    STANDALONE_STYLE,
    VIEWS_JS,
    VOID_TAGS,
    SiteImages,
    diff_content,
    has_mermaid_unit,
    math_script,
    mermaid_script,
    pair_script,
    rebase_relative_url,
    regenerated_images,
    safe_url,
    sanitize_fragment,
    source_diff,
    strip_ids,
    version_of,
) = (
    _engine.DIFF_STYLE,
    _engine.FOLD_JS,
    _engine.STANDALONE_STYLE,
    _engine.VIEWS_JS,
    _engine.VOID_TAGS,
    _engine.SiteImages,
    _engine.diff_content,
    _engine.has_mermaid_unit,
    _engine.math_script,
    _engine.mermaid_script,
    _engine.pair_script,
    _engine.rebase_relative_url,
    _engine.regenerated_images,
    _engine.safe_url,
    _engine.sanitize_fragment,
    _engine.source_diff,
    _engine.strip_ids,
    _engine.version_of,
)

ID_RE = re.compile(r'(?is)\bid\s*=\s*["\']([^"\']+)["\']')

# The generator stamps this into its own output's <head> so a later run can
# recognise — and refuse to diff — a "What changed" page it produced earlier.
# Diffing our own artifact is never meaningful: a stale what-changed.html left in
# the deployed tree (or a pr-preview tree fed in as an input) would otherwise show
# up as a spurious "new"/"changed" page in the very diff it is the output of.
WHAT_CHANGED_MARKER = "asta-what-changed"
WHAT_CHANGED_META = f'<meta name="generator" content="{WHAT_CHANGED_MARKER}">'
_MARKER_RE = re.compile(
    r'(?is)<meta\b[^>]*\bname\s*=\s*["\']generator["\'][^>]*'
    r'\bcontent\s*=\s*["\']' + re.escape(WHAT_CHANGED_MARKER) + r'["\']'
)
_LEGACY_WC_TITLE_RE = re.compile(r"(?is)<title>\s*What changed\s*(?:&middot;|·)")


def is_what_changed_artifact(doc):
    """True when `doc` is a "What changed" page this generator produced.

    Detected by the self-identifying generator meta tag, with a fallback to the
    legacy title/wrapper signature for pages generated before the marker existed.
    Only the document head is needed, so callers may pass a truncated prefix.
    """
    if _MARKER_RE.search(doc):
        return True
    return bool(_LEGACY_WC_TITLE_RE.search(doc)) and "wc-scope" in doc


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


_DIV_OPEN_RE = re.compile(r"(?is)<div\b[^>]*>")
_COMPUTED_PARTS_RE = re.compile(r"(?is)<(?:img|table|script|iframe)\b")


def without_diagram_cells(content):
    """`content` without the output cells that hold a drawing and nothing
    computed: a Graphviz cell's inline svg, a Mermaid cell's text. Both are
    static (the engine's `inline svg` and `diagram text` kinds, which
    `holds_drawing` recognises), so a page that holds one is compared like any
    page, not linked. A cell is a `div` with `cell-output-display` among its
    classes, whatever others it has."""
    out, pos = [], 0
    for m in _DIV_OPEN_RE.finditer(content):
        if m.start() < pos or "cell-output-display" not in _engine.classes_of(
            m.group(0)
        ):
            continue
        end = _engine.matching_close(content, m.end(), "div")
        if end is None:
            continue
        cell = content[m.start() : end]
        if _engine.holds_drawing(cell) and not _COMPUTED_PARTS_RE.search(cell):
            out += [content[pos : m.start()]]
            pos = end
    return "".join(out + [content[pos:]])


def has_computed_output(content):
    """True when the rendered content embeds executable/computed output."""
    return bool(COMPUTED_MARKERS.search(without_diagram_cells(content)))


SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1>")
SCRIPT_RE = re.compile(r"(?is)<script\b[^>]*>.*?</script>")


def strip_volatile(content, rel=""):
    """Sanitize an embedded body to inert, allowlisted static HTML: what the
    engine's table of kinds keeps (`sanitize_fragment`), relative links rebased
    from `rel`, ids dropped.

    The diff page ships its own single script and styles. Source markup must not
    execute here through scripts, event handlers, active elements, CSS, or
    executable URLs; a drawing is kept only as a safe subset.
    """
    return sanitize_fragment(content, rel)


def is_script_heavy(content):
    """True when inline <script> is the bulk of a page.

    Catches bespoke client-rendered pages that carry no framework marker
    `has_computed_output` would recognise — e.g. a self-contained report that is
    an empty container plus one large inline data payload the script expands on
    load. A prose page's content region carries essentially no script, so the
    ratio cleanly separates the two.
    """
    script_bytes = sum(len(m.group(0)) for m in SCRIPT_RE.finditer(content))
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


_EMPTY_EL_RE = re.compile(r"(?is)<([a-zA-Z0-9]+)\b[^>]*>\s*</\1>")


_PRE_RE = re.compile(r"(?is)<pre\b.*?</pre>")


def code_text(content):
    """The text of each code block of a fragment, whitespace exactly as written:
    in a code block whitespace is part of the code, unlike elsewhere."""
    return [
        html.unescape(re.sub(r"(?s)<[^>]+>", "", block))
        for block in _PRE_RE.findall(content)
    ]


def markup_signature(content):
    """A page's *reader-visible* signature: text plus visible formatting.

    Keeps inline/structural tags and their content (so wrapping a word in
    `<strong>` — a visible formatting change — still registers) but drops the
    markup a reader never sees: `<script>`/`<style>`, `id="..."` attributes, and
    empty elements (an anchor span `<span id="x"></span>` renders nothing). Two
    pages with equal signatures but differing raw HTML changed only non-visible
    markup — the case that should be annotated, not word-diffed.
    """
    s = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", " ", content)
    s = strip_ids(s)
    prev = None
    while prev != s:  # collapse nested empties too
        prev = s
        s = _EMPTY_EL_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def markup_only_summary(old_content, new_content, link):
    """Annotate a prose page whose only change is non-visible markup.

    The rendered text a reader sees is identical; only invisible markup differs —
    most commonly a Quarto cross-reference anchor (`[]{#id}` renders to an empty
    `<span id="id"></span>`), or an id/attribute-only edit. Embedding the whole
    page tagged "changed" would highlight nothing (an empty anchor has no visible
    text), which reads as a dropped diff. Describe the change and link out instead.
    """
    old_ids = set(ID_RE.findall(old_content))
    new_ids = set(ID_RE.findall(new_content))
    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    bits = []
    if added:
        bits.append(
            ("anchors added: " if len(added) > 1 else "anchor added: ")
            + ", ".join("#" + a for a in added)
        )
    if removed:
        bits.append(
            ("anchors removed: " if len(removed) > 1 else "anchor removed: ")
            + ", ".join("#" + r for r in removed)
        )
    detail = "; ".join(bits) if bits else "attribute/markup-only change"
    note = f"No visible text changed on this page — only non-visible markup ({detail})"
    if link:
        return (
            f'<p class="wc-note">{html.escape(note)} — '
            f'<a href="{html.escape(link)}">open the full page</a>.</p>'
        )
    return f'<p class="wc-note">{html.escape(note)}.</p>'


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


def list_pages(root, out_path=None, paper_dirs=(), reserved_local_output=False):
    """Map rel-path -> abs-path for every rendered `.html` under `root`.

    Skips generated "What changed" artifacts by exact output path or the
    generator's self-identifying marker. Local callers also reserve the root
    comparison filename and asset directory; other callers preserve legitimate
    pages with those names. Paper output
    stays in each paper's own section, including when the old site lacks a manifest.
    """
    pages = {}
    excluded = os.path.realpath(out_path) if out_path else None
    for dirpath, dirs, files in os.walk(root):
        if os.path.abspath(dirpath) == os.path.abspath(root):
            # Quarto's support files (e.g. reveal.js's speaker view) are not pages.
            dirs[:] = [name for name in dirs if name != "site_libs"]
        if reserved_local_output and os.path.abspath(dirpath) == os.path.abspath(root):
            # Local comparisons retain their rendered assets here. They are
            # supporting output, never another set of source pages to compare.
            dirs[:] = [name for name in dirs if name != "what-changed-assets"]
            files = [name for name in files if name != "what-changed.html"]
        for f in files:
            if not f.endswith(".html"):
                continue
            full = os.path.join(dirpath, f)
            if os.path.commonpath(
                (os.path.realpath(root), os.path.realpath(full))
            ) != os.path.realpath(root):
                continue
            if excluded and os.path.realpath(full) == excluded:
                continue
            rel = os.path.relpath(full, root)
            parts = rel.split(os.sep)
            if parts[0] == "paper-previews" and (
                any(
                    parts[: len(name.split("/")) + 1]
                    == ["paper-previews", *name.split("/")]
                    for name in paper_dirs
                )
                or any(
                    os.path.isfile(os.path.join(root, *parts[:i], "preview.json"))
                    for i in range(2, len(parts))
                )
            ):
                continue
            try:
                with open(full, encoding="utf-8", errors="replace") as fh:
                    if is_what_changed_artifact(fh.read(4096)):
                        continue
            except (OSError, UnicodeDecodeError):
                continue
            pages[rel] = full
    return pages


# The paper's viewer works as on its own page: the switch picks the marked or
# the clean PDF, ⤢ gives it the whole window, and Esc gives the report back. The
# paper's header (title, file, the same switch and ⤢) drives it; the viewer's own
# bar shows only in the whole window, to leave it.
PAPER_JS = r"""
(function () {
  "use strict";
  document.querySelectorAll(".paper-view").forEach(function (view) {
    var frame = view.querySelector("object");
    var expand = view.querySelector(".paper-expand");
    var buttons = view.querySelectorAll(".paper-modes button");
    var head = view.closest("section") ? view.closest("section").querySelector(".wc-head") : null;
    var headModes = head ? head.querySelectorAll("[data-wc-pdf]") : [];
    var headExpand = head ? head.querySelector(".wc-expand") : null;
    // The header's switch presses the viewer's own button for the same PDF.
    Array.prototype.forEach.call(headModes, function (mode) {
      mode.addEventListener("click", function () {
        Array.prototype.forEach.call(buttons, function (button) {
          if (button.getAttribute("data-pdf") === mode.getAttribute("data-wc-pdf")) button.click();
        });
      });
    });
    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        Array.prototype.forEach.call(headModes, function (mode) {
          mode.setAttribute("aria-pressed",
            String(mode.getAttribute("data-wc-pdf") === button.getAttribute("data-pdf")));
        });
        var next = frame.cloneNode(true);
        next.setAttribute("data", button.getAttribute("data-pdf") + "#navpanes=0&view=FitH");
        // Where a browser can't show the PDF inline, its link opens the same one.
        var fallback = next.querySelector("a");
        if (fallback) fallback.setAttribute("href", button.getAttribute("data-pdf"));
        frame.replaceWith(next);
        frame = next;
        buttons.forEach(function (other) {
          other.setAttribute("aria-pressed", String(other === button));
        });
      });
    });
    // The reader's place is kept relative to the paper's section: while the
    // paper has the whole window it leaves the page, the page gets shorter, and
    // the PDF settles back in over a moment, so the browser would otherwise
    // leave the reader elsewhere (scroll anchoring is off while it settles).
    var section = view.closest("section") || view;
    var offset = 0;
    function top() {
      return section.getBoundingClientRect().top + window.scrollY;
    }
    function setFull(full) {
      if (full === view.classList.contains("paper-full")) return;
      var root = document.documentElement;
      if (full) offset = window.scrollY - top();
      else root.style.overflowAnchor = "none";
      view.classList.toggle("paper-full", full);
      document.body.style.overflow = full ? "hidden" : "";
      expand.setAttribute("aria-pressed", String(full));
      expand.title = full ? "Back to the report" : "Give the paper the whole window";
      if (headExpand) headExpand.setAttribute("aria-pressed", String(full));
      // A key pressed inside the PDF goes to the browser's PDF viewer, not to
      // the page: the focus stays on a bar's button, so that Escape reaches us
      // (the viewer's own bar in the whole window, the header's after it).
      (full || !headExpand ? expand : headExpand).focus({ preventScroll: true });
      if (full) return;
      var back = function () { window.scrollTo(0, top() + offset); };
      requestAnimationFrame(function () {
        back();
        setTimeout(back, 150);
        setTimeout(function () { back(); root.style.overflowAnchor = ""; }, 500);
      });
    }
    function toggle() { setFull(!view.classList.contains("paper-full")); }
    expand.addEventListener("click", toggle);
    if (headExpand) headExpand.addEventListener("click", toggle);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && view.classList.contains("paper-full")) setFull(false);
    });
  });
})();
"""

# Quarto picks light or dark only in the browser (author default, then the
# reader's stored toggle), so the diff page repeats that choice on load: layer
# the active theme over the primary sheets and mark the mode for DIFF_STYLE.
# Mirrors the `quarto-color-scheme` sentinel in Quarto's before-body template.
MODE_JS = """
(() => {
  const root = document.documentElement;
  let stored = null;
  try { stored = window.localStorage.getItem("quarto-color-scheme"); } catch (e) {}
  let dark = root.dataset.wcMode === "dark";
  // A single-theme site has no toggle; a preference saved on another page
  // must not change the diff palette without a corresponding stylesheet.
  const hasAlternate = document.querySelector("link.quarto-color-scheme.quarto-color-alternate:not(.quarto-color-scheme-extra)");
  if (hasAlternate) {
    if (stored === "alternate" || stored === "default") dark = stored === "alternate";
    else if (root.dataset.wcFollowSystem === "true")
      dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  const mode = dark ? "dark" : "light";
  root.dataset.wcMode = mode;
  document.querySelectorAll("link.quarto-color-scheme, link.quarto-color-scheme-extra").forEach((link) => {
    // Quarto keeps primary styles enabled and layers the alternate over them.
    // Extra sheets are render-time helpers and are disabled in either mode.
    const enabled = !link.classList.contains("quarto-color-scheme-extra") &&
      (!link.classList.contains("quarto-color-alternate") || link_mode(link) === mode);
    link.rel = enabled ? "stylesheet" : "disabled-stylesheet";
  });
  document.body.classList.remove("quarto-light", "quarto-dark");
  document.body.classList.add("quarto-" + mode);
  function link_mode(link) {
    if (link.dataset.mode) return link.dataset.mode.toLowerCase();
    return link.classList.contains("quarto-color-alternate") ? "dark" : "light";
  }
})();
"""


# The page around the wrapper when what-changed.py writes the whole document.
PAGE_STYLE = """
:root { color-scheme: light dark; }
body { margin: 0; background: #fff; }
@media (prefers-color-scheme: dark) { body { background: #0d1117; } }
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
        # Quarto ships the inactive mode's sheets as prefetch/disabled links.
        if re.search(
            r'rel\s*=\s*["\']?[^"\'>]*stylesheet', tag, re.I
        ) or _is_color_scheme_link(tag):
            parts.append(rebase_urls(tag, depth))
    for m in re.finditer(r"(?is)<style\b[^>]*>.*?</style>", head):
        parts.append(rebase_urls(m.group(0), depth))
    return "\n".join(parts) if parts else None


def _link_classes(tag):
    classes = re.search(r"\bclass\s*=\s*[\"']([^\"']*)[\"']", tag, re.I)
    return set(classes.group(1).split()) if classes else set()


def _is_color_scheme_link(tag):
    return bool(
        _link_classes(tag) & {"quarto-color-scheme", "quarto-color-scheme-extra"}
    )


def _link_mode(tag):
    mode = re.search(r'\bdata-mode\s*=\s*["\'](light|dark)["\']', tag, re.I)
    if mode:
        return mode.group(1).lower()
    return "dark" if "quarto-color-alternate" in _link_classes(tag) else "light"


def set_theme_mode(theme_css, mode):
    """Keep primary styles, layer the active alternate, and disable extra sheets."""

    def fix(m):
        tag = m.group(0)
        if not _is_color_scheme_link(tag):
            return tag
        classes = _link_classes(tag)
        enabled = "quarto-color-scheme-extra" not in classes and (
            "quarto-color-alternate" not in classes or _link_mode(tag) == mode
        )
        rel = "stylesheet" if enabled else "disabled-stylesheet"
        tag = re.sub(r'\srel\s*=\s*(["\'])[^"\']*\1', "", tag, flags=re.I)
        return re.sub(r"(?i)^<link\b", f'<link rel="{rel}"', tag)

    return re.sub(r"(?is)<link\b[^>]*>", fix, theme_css)


def extract_default_mode(doc):
    """Return (mode, follows_system): the mode a fresh visitor sees.

    Quarto renders the light sheet first and switches in the browser, so the
    author's choice is read from its color-scheme script before the links.
    """
    author = re.search(r"\bauthorPrefersDark\s*=\s*(true|false)\b", doc)
    follows_system = bool(
        re.search(r"\bdarkModeDefault\s*=\s*queryPrefersDark\.matches", doc)
    )
    if author:
        return ("dark" if author.group(1) == "true" else "light"), follows_system
    return extract_theme_mode(doc) or "light", follows_system


def extract_theme_mode(doc):
    """Return the first Bootstrap stylesheet's mode (light or dark), if present."""
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
    return rewrite_style_urls(
        text, lambda url: url[len(prefix) :] if url.startswith(prefix) else url
    )


def rewrite_style_urls(text, rewrite):
    """Rewrite CSS URLs in inline styles, preserving quoting and raw CSS text.

    Tokenize comments and strings as well as url() and string-form @import so
    apparent URLs inside comments or content strings are left alone. Quoted
    paths can contain whitespace, parentheses, and backslash-escaped quotes.
    """
    string = r"""(?:"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*')"""
    tokens = re.compile(
        rf"(?P<comment>/\*[\s\S]*?\*/)"
        rf"|\burl\(\s*(?P<url>{string}|(?:\\[\s\S]|[^\\\s\"'()])*)\s*\)"
        rf"|@import\s+(?P<import>{string})"
        rf"|{string}",
        re.I,
    )

    def token(match):
        group = "url" if match.group("url") is not None else "import"
        value = match.group(group)
        if value is None:
            return match[0]
        quote = value[:1] if value.startswith(('"', "'")) else ""
        url = value[1:-1] if quote else value
        start, end = match.span(group)
        start -= match.start()
        end -= match.start()
        return match[0][:start] + quote + rewrite(url) + quote + match[0][end:]

    return re.sub(
        r"(?is)(<style\b[^>]*>)(.*?)(</style>)",
        lambda match: match[1] + tokens.sub(token, match[2]) + match[3],
        text,
    )


def link_citations(body, link):
    """Resolve excerpt citations against the full page bibliography."""
    return re.sub(
        r'href="#(ref-[^"]*)"',
        lambda m: f'href="{html.escape(link)}#{m.group(1)}"',
        body,
    )


def page_title(doc, rel):
    m = re.search(r"(?is)<title>(.*?)</title>", doc)
    if m:
        # <title> holds entity-encoded text; decode it so callers escape it once.
        # Trim only HTML whitespace so non-breaking spaces remain part of the title.
        t = re.sub(r"[ \t\r\n\f]+", " ", html.unescape(m.group(1))).strip(" \t\r\n\f")
        if t:
            return t
    return rel


def anchor_id(rel):
    return "p-" + re.sub(r"[^a-zA-Z0-9]+", "-", rel).strip("-")


class TocEntry(NamedTuple):
    """One line of the overview at the top: a page, a deck or a paper.

    anchor  the id of its section
    title   its title as a reader names it, plain text
    state   `changed`, `new` or `removed`
    label   what the tag beside the title says; empty for a plain change, whose
            count says it
    file    the file it is shown from
    detail  how much changed, as a reader counts it ("14 changes"); empty when
            the page has none to count (a new page, a card)"""

    anchor: str
    title: str
    state: str
    label: str
    file: str
    detail: str


# What marks a change in a diff body: the engine's own marks (see FOLD_JS).
_CHANGE_TAGS = {"ins", "del"}
_CHANGE_CLASSES = {
    "wc-edit-old",
    "wc-edit-new",
    "wc-block-added",
    "wc-block-removed",
    "wc-link-was",
    "wc-link-changed",
    "wc-fmt-changed",
    "wc-ev-chip",
}
# The blocks a change is counted by: one count for each of these that holds a
# mark and holds no other of these that does (a list item whose paragraph is
# edited is that paragraph's change, a row is one change however many cells, and
# whatever its cells hold: the row owns the marks inside it).
_LEAF_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "pre"} | {
    "figcaption",
    "dt",
    "dd",
}


class _ChangeCounter(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.count = 0
        self.any = False
        self.stack = []  # [tag, marked, holds_marked_leaf]

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            if _marked(tag, attrs):
                self._mark()
            return
        self.stack.append([tag, False, False])
        if _marked(tag, attrs):
            self._mark()

    def handle_startendtag(self, tag, attrs):
        if _marked(tag, attrs):
            self._mark()

    def _mark(self):
        self.any = True
        for frame in self.stack:
            frame[1] = True

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] != tag:
                continue
            _, marked, holds = self.stack[index]
            del self.stack[index:]
            if tag in _LEAF_TAGS and marked:
                # A row owns the marks inside it: its cells' paragraphs are the
                # row's one change, not each their own.
                if any(frame[0] == "tr" for frame in self.stack):
                    break
                if not holds:
                    self.count += 1
                for frame in self.stack:
                    frame[2] = True
            break


def _marked(tag, attrs):
    classes = set((dict(attrs).get("class") or "").split())
    return tag in _CHANGE_TAGS or bool(classes & _CHANGE_CLASSES)


def count_changes(body):
    """How many changes a diff body holds, as a reader counts them: the blocks
    that hold a mark (a paragraph, a list item, a row, a figure's paragraph),
    each once; at least one when anything is marked."""
    counter = _ChangeCounter()
    counter.feed(body)
    counter.close()
    return counter.count or int(counter.any)


_TITLE_SPLIT_RE = re.compile(r"\s[\u2013\u2014-]\s")


def site_name(titles):
    """The name Quarto adds to every page's title ("Page – Site"): the ending
    that two or more pages share, else None (one page cannot say which part of
    its title is the site's)."""
    endings = Counter(
        _TITLE_SPLIT_RE.split(t)[-1].strip()
        for t in titles
        if _TITLE_SPLIT_RE.search(t)
    )
    for name, n in endings.most_common(1):
        if n > 1 and name:
            return name
    return None


def short_title(title, site):
    """A page's title without the site's name, which every page repeats."""
    if site:
        # "Page – Site" for a page, "Site – Page" for a deck ("Slides · Site – Page")
        title = re.sub(rf"\s[\u2013\u2014-]\s{re.escape(site)}\s*$", "", title)
        title = re.sub(rf"(^|·\s*){re.escape(site)}\s[\u2013\u2014-]\s", r"\1", title)
    return title.strip()


def head_title(path, rel):
    """The <title> of the rendered page at `path` (read from its head)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return page_title(f.read(16384), rel)
    except OSError:
        return rel


# The views of a diff's control, in order: the diffs (Source, where there is one,
# Changes marked, Before / after), then Clean, the one view that is no diff; and the
# one it opens on.
VIEWS = (
    ("source", "Source"),
    ("marked", "Changes marked"),
    ("before", "Before / after"),
    ("clean", "Clean"),
)
# What the header and the overview say of a page whose rendered content no reader
# sees change but whose source did.
SOURCE_ONLY = "only its source changed"
DEFAULT_VIEW = "marked"
# What a page's own source may be called, by the rendered page's name, and the
# most of it that is read (a notebook's JSON can be megabytes). The workspace's
# workflow lists the same suffixes where it reads the committed sources; a test
# keeps the two equal.
SOURCE_SUFFIXES = (".qmd", ".md", ".ipynb", ".Rmd", ".rmd", ".markdown")
SOURCE_LIMIT = 512 * 1024


def counts_as_change(old_text, new_text):
    """Whether two versions of a source differ as a reviewer would count it, the
    rule of `git diff --ignore-blank-lines --ignore-space-at-eol`: not when they
    differ only in blank lines or in whitespace at the end of lines. Any other
    spacing counts, inside a line or in indentation: in code it can matter."""

    def lines(text):
        kept = (line.rstrip() for line in text.splitlines())
        return [line for line in kept if line]

    return lines(old_text) != lines(new_text)


class SourceFiles:
    """The project's own files at both commits, where `asta workspace
    what-changed` has them, so that a page can show its source (.qmd, .md or
    .ipynb) at both, and a page whose only change is in its source is not lost."""

    def __init__(self, old_root=None, new_root=None):
        self.roots = (old_root, new_root)

    @staticmethod
    def find(root, rel):
        """(path, text) of the source of the rendered page `rel` under `root`, else None."""
        if not root:
            return None
        base = os.path.realpath(root)
        stem = os.path.splitext(rel.replace(os.sep, "/"))[0]
        for suffix in SOURCE_SUFFIXES:
            path = os.path.join(root, stem + suffix)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            if os.path.commonpath((base, os.path.realpath(path))) != base:
                continue
            try:
                if os.path.getsize(path) > SOURCE_LIMIT:
                    return None
                with open(path, encoding="utf-8", errors="replace") as stream:
                    return stem + suffix, stream.read()
            except OSError:
                return None
        return None

    def view(self, rel):
        """(file, html, changed) for the page `rel`: the source file's name, its
        Source view, and whether the two versions differ (`counts_as_change`); None
        where neither commit has the source."""
        old, new = (self.find(root, rel) for root in self.roots)
        if old is None and new is None:
            return None
        file = (new or old)[0]
        old_text, new_text = (old or (file, ""))[1], (new or (file, ""))[1]
        if old_text == new_text:
            return (
                file,
                '<p class="wc-note">This source is the same in both versions; what '
                "changed comes from a file it uses (a figure, data, an included "
                "file).</p>",
                False,
            )
        return (
            file,
            source_diff(old_text, new_text),
            counts_as_change(old_text, new_text),
        )


def version_templates(old_c, new_c, rel, link, images):
    """The old and the new page as published, each whole and made safe the way the
    diff's own content is (`strip_volatile`; an old image the new site does not serve
    from its old bytes, `version_of`), in a `<template>` each: inert until the page's
    script draws a view from it. Never the marked diff with its marks taken off. A
    citation (`#ref-key`) reaches its bibliography on the full page at `link`, as it
    does in the marked view."""
    out = []
    for which, content in (("old", old_c), ("new", new_c)):
        safe = version_of(strip_volatile(content, rel), which, images)
        safe = link_citations(safe, link)
        # (Made safe, it holds no template tag; the end of one is never left in it.)
        safe = re.sub(r"(?i)</template", "&lt;/template", safe)
        out.append(
            f'<template class="wc-version" data-wc-version="{which}">{safe}</template>'
        )
    return "".join(out)


def unchanged_page(output, old_c, new_c, rel, link, sources):
    """A page of the site whose rendered content no reader sees change, as `(state,
    label, body)` when its source has a change the page does not show (a comment, a
    cell option, front matter it does not print), else None. Its body is the page as
    it is, under a note: the header says only its source changed, and its Source view
    shows the change. A page made by script is the card for such pages, never the
    page: its scripts are not carried."""
    if (
        output.name not in ("site page", "page made by script")
        or old_c is None
        or new_c is None
        or not sources
    ):
        return None
    found = sources.view(rel)
    if not found or not found[2]:
        return None
    if output.name == "page made by script":
        card = summary_card(
            new_c,
            link,
            "This page renders its content with client-side scripts; no reader sees "
            "a change in it, but its source changed (open Source)",
        )
        return "changed", "changed", card
    note = (
        '<p class="wc-note">No reader sees a change on this page. Its source '
        "changed: open Source.</p>"
    )
    return "changed", "changed", note + strip_volatile(new_c, rel)


def views_control(views):
    """The control: one button to each of `views` (names of VIEWS), in the order
    of VIEWS, with DEFAULT_VIEW pressed."""
    return (
        '<span class="wc-views" role="group" aria-label="View">'
        + "".join(
            f'<button type="button" data-wc-view="{v}" '
            f'aria-pressed="{"true" if v == DEFAULT_VIEW else "false"}">{label}</button>'
            for v, label in VIEWS
            if v in views
        )
        + "</span>"
    )


def diff_header(
    title, link, state, label, file, controls="", source_file="", detail=""
):
    """The one header of a diff, on one line: the page's short title (linking
    to the page, with a tag when it is more than plain `changed`), its file, a
    plain `detail` after the file, then `controls`, the control (views_control)
    and any button.

    title, label, file, source_file and detail are plain text, escaped here."""
    name = html.escape(title)
    if link:
        name = f'<a href="{html.escape(link, quote=True)}">{name}</a>'
    tag = (
        ""
        if label == "changed"
        else f' <span class="tag {state}">{html.escape(label)}</span>'
    )
    detail_html = (
        f'<span class="wc-detail">{html.escape(detail)}</span>' if detail else ""
    )
    shown = html.escape(file, quote=True)
    source = (
        f' data-source="{html.escape(source_file, quote=True)}"' if source_file else ""
    )
    return (
        '<div class="wc-head"><span class="wc-head-left">'
        f'<h2 class="wc-title">{name}{tag}</h2>'
        f'<code class="wc-file" data-rendered="{shown}"{source}>{html.escape(file)}</code>'
        f"{detail_html}"
        f'</span><span class="wc-head-right">{controls}</span></div>'
    )


def source_part(found):
    """What a diff's section holds for its Source view: `(source_file, html)` from
    `SourceFiles.view`'s answer, or ("", "") when there is none."""
    if not found:
        return "", ""
    file, body, _ = found
    return file, f'<div class="wc-source" hidden>{body}</div>'


def overview(entries):
    """The overview at the top: what this edit changed, a line to each page, deck
    or paper (its short title, its file, how much changed), as a list."""
    n = len(entries)
    items = []
    for e in entries:
        line = f'<a href="#{e.anchor}">{html.escape(e.title)}</a>'
        if e.label:
            line += f' <span class="tag {e.state}">{html.escape(e.label)}</span>'
        line += f' &middot; <code class="toc-file">{html.escape(e.file)}</code>'
        if e.detail:
            line += f' &middot; <span class="toc-count">{html.escape(e.detail)}</span>'
        items.append(f"<li>{line}</li>")
    return (
        f'<nav class="toc"><p class="toc-head">This edit changed {n} '
        f"thing{'' if n == 1 else 's'}:</p><ul>{''.join(items)}</ul></nav>"
    )


def _is_slide_deck(doc):
    # A site's own CSS may use a class named "reveal". Quarto reveal.js decks
    # carry the runtime's stylesheet, which identifies the actual deck format.
    return bool(
        re.search(
            r'(?is)<link\b[^>]*\bhref\s*=\s*["\'](?:[^"\']*/)?reveal(?:\.min)?\.css(?:[?#][^"\']*)?["\']',
            doc,
        )
    )


def pick_template(new_pages):
    """Choose the shallowest styled site page to borrow the site theme from.

    A root-level page (e.g. index.html) keeps asset URLs simplest to rebase.
    Pages without CSS cannot supply a theme and are skipped. A reveal.js deck
    carries the deck's styling, not the site's, so it is used only when no styled
    ordinary page exists.
    Returns (doc_html, depth) or (None, 0) if nothing suitable exists.
    """
    fallback = (None, 0)
    for rel in sorted(new_pages, key=lambda r: (r.replace(os.sep, "/").count("/"), r)):
        depth = rel.replace(os.sep, "/").count("/")
        try:
            with open(new_pages[rel], encoding="utf-8") as f:
                doc = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        if not extract_theme_css(doc, depth):
            continue
        if not _is_slide_deck(doc):
            return doc, depth
        if fallback[0] is None:
            fallback = (doc, depth)
    return fallback


def paper_identity(paper_dir):
    label = (
        "Paper"
        if paper_dir == "paper"
        else " / ".join(
            html.escape(part.replace("-", " ").title().replace("Latex", "LaTeX"))
            for part in paper_dir.split("/")
        )
    )
    section_id = (
        "paper-diff"
        if paper_dir == "paper"
        else f"paper-diff-{paper_dir.encode().hex()}"
    )
    return label, section_id


def paper_state(new_root, paper_dir):
    """The paper preview's manifest (preview.json) as a dict, or None."""
    manifest = os.path.join(new_root, "paper-previews", paper_dir, "preview.json")
    if not os.path.isfile(manifest):
        return None
    try:
        with open(manifest, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return state if isinstance(state, dict) else None


def paper_file(new_root, paper_dir):
    """The paper's main document, as the viewer and the overview name it: what
    the manifest says (`main`), else main.tex, which the preview takes first."""
    main = (paper_state(new_root, paper_dir) or {}).get("main")
    return f"{paper_dir}/{main if isinstance(main, str) and main else 'main.tex'}"


def paper_preview(old_root, new_root, paper_dir="paper"):
    state = paper_state(new_root, paper_dir)
    if state is None:
        return None
    if not state.get("changed"):
        return None
    label, section_id = paper_identity(paper_dir)
    if state.get("removed"):
        section = (
            f'<section class="page-diff removed" id="{section_id}">'
            + diff_header(
                html.unescape(label),
                "",
                "removed",
                "removed",
                paper_file(new_root, paper_dir),
            )
            + '<p class="wc-note">Paper removed; no paper PDF is published in this preview.</p>'
            "</section>"
        )
        return section, "removed"

    def paper_url(filename):
        return html.escape(
            f"paper-previews/{quote(paper_dir, safe='/')}/{filename}", quote=True
        )

    pdf = paper_url("what-changed.pdf" if state.get("diff") else "main.pdf")
    if state.get("new"):
        note = "Paper added; the current paper PDF is available."
    elif state.get("diff") and state.get("other_inputs"):
        note = "LaTeX edits are highlighted; other paper inputs may not be."
    elif state.get("diff"):
        note = ""  # the marked PDF says what changed
    elif state.get("unhighlighted"):
        note = "LaTeX inputs changed, but the diff has no marked text; the current PDF is available without highlights."
    elif state.get("other_inputs"):
        note = "Paper inputs changed; the current PDF is available without highlights."
    else:
        note = "The LaTeX diff could not be built; the current paper PDF is available."
    status = "new" if state.get("new") else "changed"
    # The paper reads in the same viewer as on its own page, a page tall here,
    # with the same switch between its changes marked and the clean paper and
    # the same ⤢ for the whole window, so that it reads one way wherever the
    # site shows it.
    modes = ""
    if state.get("diff"):
        modes = (
            '<span class="paper-modes" role="group" aria-label="Which PDF">'
            f'<button type="button" data-pdf="{paper_url("what-changed.pdf")}" '
            'aria-pressed="true">Changes marked</button>'
            f'<button type="button" data-pdf="{paper_url("main.pdf")}" '
            'aria-pressed="false">Clean</button></span>'
        )
    # The bar reads the same in the page and in the whole window: the paper's
    # title and file on the left; the switch and the whole-window button at the
    # far right.
    path = paper_file(new_root, paper_dir)
    file = html.escape(path)
    viewer = (
        '<div class="paper-view"><div class="paper-bar">'
        f'<strong class="paper-title">{label}</strong>'
        f'<code class="paper-file">{file}</code>{modes}'
        '<button type="button" class="paper-expand" aria-pressed="false" '
        'title="Give the paper the whole window">&#x2922;</button></div>'
        f'<object data="{pdf}#navpanes=0&amp;view=FitH" type="application/pdf" '
        f'title="{label}"><a href="{pdf}">Open the paper PDF</a></object></div>'
    )
    note_html = f'<p class="wc-note">{note}</p>' if note else ""
    # The header holds the title and file, then the same two views as the viewer's
    # own switch (Changes marked, Clean), which drive it, and the whole-window
    # button at the far right; the viewer's own bar shows only in the whole window.
    controls = ""
    if state.get("diff"):
        controls = (
            '<span class="wc-views" role="group" aria-label="Which PDF">'
            f'<button type="button" data-wc-pdf="{paper_url("what-changed.pdf")}" '
            'aria-pressed="true">Changes marked</button>'
            f'<button type="button" data-wc-pdf="{paper_url("main.pdf")}" '
            'aria-pressed="false">Clean</button></span>'
        )
    controls += (
        '<button type="button" class="wc-expand" aria-pressed="false" '
        'title="Give the paper the whole window">&#x2922;</button>'
    )
    section = (
        f'<section class="page-diff {status}" id="{section_id}">'
        + diff_header(html.unescape(label), "", status, status, path, controls)
        + f"{note_html}{viewer}</section>"
    )
    return section, status


class SlideParser(HTMLParser):
    """Read Reveal's slide container without mistaking content sections for slides."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.tags = []
        self.nodes = []
        self.root = None
        self.doc = ""
        self._lines = [0]

    def feed(self, data):
        # Offsets let a slide keep its raw markup and the deck its HTML outside the
        # slides, which deck-review.py compares to skip unchanged slides' pixels.
        # HTMLParser counts only LF as a newline, and feed() receives a chunk.
        # Other Unicode line separators remain ordinary source characters.
        self._lines.extend(
            len(self.doc) + match.end() for match in re.finditer("\n", data)
        )
        self.doc += data
        super().feed(data)

    def _offset(self):
        line, column = self.getpos()
        return self._lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        in_reveal = any("reveal" in classes for _, classes in self.tags)
        start = self._offset()
        if self.root is None and tag == "div" and "slides" in classes and in_reveal:
            self.root = {"tag": tag, "attrs": dict(attrs), "parts": [], "open": ""}
            self.root["inner"] = start + len(self.get_starttag_text())
            self.nodes.append(self.root)
        elif self.nodes:
            node = {
                "tag": tag,
                "attrs": dict(attrs),
                "parts": [],
                "open": self.get_starttag_text(),
                "start": start,
            }
            self.nodes[-1]["parts"].append(node)
            if tag not in VOID_TAGS:
                self.nodes.append(node)
        if tag not in VOID_TAGS:
            self.tags.append((tag, classes))

    def handle_startendtag(self, tag, attrs):
        if self.nodes:
            self.nodes[-1]["parts"].append(self.get_starttag_text())

    def handle_endtag(self, tag):
        start = self._offset()
        end = self.doc.find(">", start) + 1 or len(self.doc)
        for index in range(len(self.nodes) - 1, -1, -1):
            if self.nodes[index]["tag"] == tag:
                for node in self.nodes[index:]:
                    node.setdefault("end", end)
                if self.nodes[index] is self.root:
                    self.root["close"] = start
                del self.nodes[index:]
                break
        for index in range(len(self.tags) - 1, -1, -1):
            if self.tags[index][0] == tag:
                del self.tags[index:]
                break

    def handle_data(self, data):
        if self.nodes:
            self.nodes[-1]["parts"].append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")

    @staticmethod
    def markup(node):
        if isinstance(node, str):
            return node
        body = "".join(SlideParser.markup(part) for part in node["parts"])
        closing = "" if node["tag"] in VOID_TAGS else f"</{node['tag']}>"
        return node["open"] + body + closing

    def slides(self):
        if self.root is None:
            return None
        slides = []
        inner = self.doc[self.root["inner"] : self.root.get("close", len(self.doc))]
        # Deck-wide inputs: the HTML outside the slides plus any style, script or
        # link inside them, since those can restyle every slide.
        frame = (
            self.doc[: self.root["inner"]],
            self.doc[self.root.get("close", len(self.doc)) :],
            re.findall(
                r"<style\b.*?</style\s*>|<script\b.*?</script\s*>|<link\b[^>]*>",
                inner,
                re.S | re.I,
            ),
        )
        horizontal = [
            part
            for part in self.root["parts"]
            if isinstance(part, dict) and part["tag"] == "section"
        ]
        for h, section in enumerate(horizontal):
            parts = [
                part
                for part in section["parts"]
                if not isinstance(part, str) or part.strip()
            ]
            stack = bool(parts) and all(
                isinstance(part, dict) and part["tag"] == "section" for part in parts
            )
            for v, node in enumerate(parts if stack else [section]):
                ident = node["attrs"].get("id", "")
                body = normalize("".join(self.markup(part) for part in node["parts"]))
                raw = self.doc[node["start"] : node.get("end", len(self.doc))]
                slides.append(
                    {
                        "id": ident,
                        "body": body,
                        # The stack's own tag too: its attributes apply to its slides.
                        "raw": (section["open"] if stack else "") + raw,
                        "position": (h, v if stack else None),
                        "span": (node["start"], node.get("end", len(self.doc))),
                        "frame": frame,
                        "anchor": quote(ident, safe="")
                        if ident
                        else f"{h}/{v}"
                        if stack
                        else str(h),
                    }
                )
        return slides


def reveal_slides(doc):
    if not doc:
        return None
    parser = SlideParser()
    parser.feed(doc)
    return parser.slides()


def match_slides(old, new):
    """Anchor unchanged bodies before IDs, which Quarto derives from titles."""
    matcher = difflib.SequenceMatcher(
        None,
        [slide["body"] for slide in old],
        [slide["body"] for slide in new],
        autojunk=False,
    )
    pairs = {
        new_index: old_index
        for a, b, size in matcher.get_matching_blocks()
        for old_index, new_index in zip(range(a, a + size), range(b, b + size))
    }
    old_ids = {slide["id"]: index for index, slide in enumerate(old) if slide["id"]}
    used = set(pairs.values())
    pairs.update(
        {
            index: old_ids[slide["id"]]
            for index, slide in enumerate(new)
            if index not in pairs
            and slide["id"] in old_ids
            and old_ids[slide["id"]] not in used
        }
    )
    unmatched_old = [index for index in range(len(old)) if index not in pairs.values()]
    unmatched_new = [index for index in range(len(new)) if index not in pairs]
    pairs.update(_pair_similar(old, new, unmatched_old, unmatched_new))
    return pairs


def _pair_similar(old, new, olds, news):
    """Pair unmatched slides in order by text similarity, e.g. a retitled slide.

    Positional pairing let an inserted slide take a retitled slide's place, so
    the edit showed as one removed and one new slide. Unrelated additions and
    removals stay unpaired.
    """
    if not olds or not news:
        return {}
    text = [re.sub(r"<[^>]+>", "", old[i]["body"]) for i in olds]
    after = [re.sub(r"<[^>]+>", "", new[j]["body"]) for j in news]

    def similar(a, b):
        matcher = difflib.SequenceMatcher(None, text[a], after[b], autojunk=False)
        if matcher.quick_ratio() < 0.5:
            return 0.0
        ratio = matcher.ratio()
        return ratio if ratio >= 0.5 else 0.0

    m, n = len(olds), len(news)
    if m * n > 2500:
        # Hirschberg alignment considers every shift, including insertions longer
        # than a positional window. Rolling score rows keep auxiliary memory
        # linear; splitting the old range bounds similarity work to O(m*n).
        def scores(a0, a1, b0, b1, reverse=False):
            row = [0.0] * (b1 - b0 + 1)
            arange = range(a1 - 1, a0 - 1, -1) if reverse else range(a0, a1)
            brange = range(b1 - 1, b0 - 1, -1) if reverse else range(b0, b1)
            for a in arange:
                diagonal = 0.0
                for j, b in enumerate(brange, 1):
                    above = row[j]
                    row[j] = max(above, row[j - 1], diagonal + similar(a, b))
                    diagonal = above
            return row

        result = {}

        def align(a0, a1, b0, b1):
            if a0 == a1 or b0 == b1:
                return
            if a1 - a0 == 1:
                b = max(range(b0, b1), key=lambda b: similar(a0, b))
                if similar(a0, b):
                    result[news[b]] = olds[a0]
                return
            mid = (a0 + a1) // 2
            left = scores(a0, mid, b0, b1)
            right = scores(mid, a1, b0, b1, reverse=True)
            cut = max(range(b1 - b0 + 1), key=lambda j: left[j] + right[-1 - j])
            del left, right  # do not retain rows on the recursion stack
            split = b0 + cut
            align(a0, mid, b0, split)
            align(mid, a1, split, b1)

        align(0, m, 0, n)
        return result
    score = [[similar(a, b) for b in range(n)] for a in range(m)]
    best = [[0.0] * (n + 1) for _ in range(m + 1)]
    for a in range(m - 1, -1, -1):
        for b in range(n - 1, -1, -1):
            take = score[a][b] + best[a + 1][b + 1] if score[a][b] else 0.0
            best[a][b] = max(best[a + 1][b], best[a][b + 1], take)
    pairs, a, b = {}, 0, 0
    while a < m and b < n:
        if score[a][b] and best[a][b] == score[a][b] + best[a + 1][b + 1]:
            pairs[news[b]] = olds[a]
            a, b = a + 1, b + 1
        elif best[a][b] == best[a + 1][b]:
            a += 1
        else:
            b += 1
    return pairs


def load_deck_review():
    """deck-review.py beside this script, or None if it cannot be loaded."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deck-review.py")
    if not os.path.exists(path):
        return None
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("deck_review", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - any failure falls back to the text diff
        print(f"what-changed: slides as text ({exc})", file=sys.stderr)
        return None
    return module


class DeckRenderer:
    """Publish marked live decks with their assets, without starting a browser."""

    def __init__(self, module, old_root, new_root, img_root, img_url):
        self.module, self.old_root, self.new_root = module, old_root, new_root
        self.img_root, self.img_url = img_root, img_url.rstrip("/")
        self.files = module.StaticFiles(old_root, new_root)
        self.used = False
        self.copied = False

    def review(self, rel, link, old, new, pairs):
        try:
            return self._review(rel, old, new, pairs)
        except Exception as exc:  # noqa: BLE001 - a deck must not abort other pages
            print(f"what-changed: slides as text ({rel}: {exc})", file=sys.stderr)
            return False

    def _review(self, rel, old, new, pairs):
        def read(root):
            path = os.path.join(root, rel)
            if os.path.commonpath(
                (os.path.realpath(root), os.path.realpath(path))
            ) != os.path.realpath(root):
                raise ValueError("deck resolves outside the site")
            if not os.path.isfile(path):
                return ""
            with open(path, encoding="utf-8") as stream:
                return stream.read()

        url = quote(rel, safe="/")
        body, before, after, marked, frames = self.module.live_review(
            rel,
            read(self.old_root),
            read(self.new_root),
            old,
            new,
            pairs,
            self.files,
            f"{self.img_url}/before/{url}",
            f"{self.img_url}/after/{url}",
            bar=False,
        )
        if body is None:
            return None
        if not self.copied:
            generated = os.path.basename(self.img_root)
            for side, root in (("before", self.old_root), ("after", self.new_root)):

                def ignore(directory, names):
                    # Preserve relative in-site links without dereferencing them.
                    # Never let runner-local files enter the Pages artifact.
                    skipped = {generated} & set(names)
                    for name in names:
                        path = os.path.join(directory, name)
                        if os.path.islink(path) and (
                            os.path.isabs(os.readlink(path))
                            or os.path.commonpath(
                                (os.path.realpath(root), os.path.realpath(path))
                            )
                            != os.path.realpath(root)
                        ):
                            skipped.add(name)
                    return skipped

                shutil.copytree(
                    root,
                    os.path.join(self.img_root, side),
                    symlinks=True,
                    ignore=ignore,
                    dirs_exist_ok=True,
                )
            self.copied = True
        for side, name, doc in (
            ("before", rel, before),
            ("after", rel, after),
            ("after", self.module.marked_path(rel), marked),
        ):
            if doc:
                path = os.path.join(self.img_root, side, name)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write(doc)
        # One slide per frame: the frame documents, and the files they all share.
        for (side, name), doc in frames.items():
            if side == "shared":
                path = os.path.join(self.img_root, self.module.FRAME_ASSETS, name)
            else:
                path = os.path.join(self.img_root, side, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as stream:
                stream.write(doc if isinstance(doc, bytes) else doc.encode("utf-8"))
        self.used = True
        return body

    def close(self):
        pass


def slides_changed(edited, total, state, reordered):
    """What the overview says of a deck's changes: "1 of 10 slides changed"."""
    if state != "changed":
        return ""
    if edited:
        return f"{edited} of {total} slide{'' if total == 1 else 's'} changed"
    return "slides reordered" if reordered else ""


def unchanged_slides(rel, link, old_doc, new_doc, sources, site):
    """A slide deck whose slides no reader sees change, as `(section, TocEntry)`
    when its source changed, else None: the header says only its source changed,
    and its Source view shows the change."""
    if old_doc is None or new_doc is None or not sources:
        return None
    found = sources.view(rel)
    if not found or not found[2]:
        return None
    source_file, source_html = source_part(found)
    label = "Slides · " + page_title(new_doc, rel)
    aid = anchor_id(rel)
    head = diff_header(
        short_title(label, site),
        link,
        "changed",
        "changed",
        rel,
        views_control(("marked", "source")),
        source_file,
        SOURCE_ONLY,
    )
    note = (
        '<div class="diff-body"><p class="wc-note">No reader sees a change in these '
        "slides. Their source changed: open Source.</p></div>"
    )
    return (
        f'<section class="page-diff changed" id="{aid}">{head}{note}{source_html}</section>',
        TocEntry(aid, label, "changed", "", rel, SOURCE_ONLY),
    )


def slide_diff(
    old_doc,
    new_doc,
    rel,
    link,
    old=None,
    new=None,
    decks=None,
    images=None,
    sources=None,
    site=None,
):
    old = (reveal_slides(old_doc) if old is None else old) or []
    new = (reveal_slides(new_doc) if new is None else new) or []
    pairs = match_slides(old, new)
    matched_order = [pairs[index] for index in sorted(pairs)]
    reordered = matched_order != sorted(matched_order)
    rendered = decks.review(rel, link, old, new, pairs) if decks else False
    if rendered is None and not reordered:
        return unchanged_slides(rel, link, old_doc, new_doc, sources, site)
    entries = [(pairs.get(index), index) for index in range(len(new))]
    entries.extend(
        (index, None) for index in range(len(old)) if index not in pairs.values()
    )
    changes = []
    for old_index, new_index in entries:
        before = old[old_index] if old_index is not None else None
        after = new[new_index] if new_index is not None else None
        if (
            before
            and after
            and before["body"] == after["body"]
            # a figure redrawn under its name leaves the slide's HTML as it was
            and not regenerated_images(
                strip_volatile(before["body"], rel),
                strip_volatile(after["body"], rel),
                images,
            )
        ):
            continue
        index, content = (
            (new_index, after["body"]) if after else (old_index, before["body"])
        )
        caption = (
            visible_text(strip_volatile(content, rel)).strip().split("\n")[0][:100]
            or f"Slide {index + 1}"
        )
        heading = html.escape(f"Slide {index + 1}: {caption}")
        if after:
            heading = f'<a href="{html.escape(link + "#/" + after["anchor"], quote=True)}">{heading}</a>'
        if before and after:
            body, changed = diff_content(
                strip_volatile(before["body"], rel),
                strip_volatile(after["body"], rel),
                images,
            )
            if not changed:
                body = '<p class="wc-note">Slide markup changed. Open the slide to inspect it.</p>'
            state = "changed"
        elif after:
            body, state = strip_volatile(content, rel), "new"
        else:
            body, state = strip_volatile(content, rel), "removed"
        changes.append(
            f'<article class="slide-diff {state}"><h3>{heading} <span class="tag {state}">{state}</span></h3><div class="diff-body">{body}</div></article>'
        )
    edited = len(changes)
    if rendered is None:
        changes = []
    elif rendered:
        changes = [rendered]
    if reordered:
        changes.insert(0, '<p class="wc-note">Slides reordered.</p>')
    if not changes:
        return unchanged_slides(rel, link, old_doc, new_doc, sources, site)
    state = "new" if old_doc is None else "removed" if new_doc is None else "changed"
    label = "Slides · " + page_title(new_doc or old_doc, rel)
    aid = anchor_id(rel)
    # The deck's views are the control's; the deck's own bar is not drawn.
    found = sources.view(rel) if sources and rendered else None
    source_file, source_html = source_part(found)
    controls = (
        views_control(("marked", "clean", "before") + (("source",) if found else ()))
        if rendered
        else ""
    )
    head = diff_header(
        short_title(label, site),
        link if new_doc else "",
        state,
        state,
        rel,
        controls,
        source_file,
    )
    detail = slides_changed(edited, len(new) if new else len(old), state, reordered)
    return (
        f'<section class="page-diff {state}" id="{aid}">{head}'
        f"{''.join(changes)}{source_html}</section>",
        TocEntry(aid, label, state, "", rel, detail),
    )


def prefix_theme_urls(css, prefix):
    """Rebase theme links, CSS url(), and @import into the retained asset tree."""

    def prefixed(url, attribute=False):
        # HTML attributes decode entities; <style> is raw text. Preserve CSS
        # ampersands (including literal entity-looking strings) byte for byte.
        value = html.unescape(url) if attribute else url
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return url
        value = prefix.rstrip("/") + "/" + value.lstrip("/")
        return html.escape(value, quote=True) if attribute else value

    css = re.sub(
        r"""(?i)(\bhref\s*=\s*)(["'])([^"']*)\2""",
        lambda match: (
            f"{match[1]}{match[2]}{prefixed(match[3], attribute=True)}{match[2]}"
        ),
        css,
    )
    return rewrite_style_urls(css, prefixed)


def _squash(content):
    return re.sub(r"\s+", " ", content).strip()


def script_page(old_c, new_c, rel, link, images):
    """A page whose content is made by running script, as (state, label, body),
    or None when it did not change. Its visible content is produced by its own
    scripts, so an inline word diff is meaningless and embedding it would run
    foreign markup here: a card with a link to the full page, for new, removed
    and changed alike. Any normalized content difference is material enough to
    report: comparing static text alone can hide changed data or client-side
    logic."""
    if old_c is not None and new_c is not None:
        if _squash(old_c) == _squash(new_c):
            return None
        return (
            "changed",
            "changed · interactive page (linked)",
            summary_card(
                new_c, link, "This page renders its content with client-side scripts"
            ),
        )
    if new_c is not None:
        return (
            "new",
            "new page · interactive (linked)",
            summary_card(
                new_c,
                link,
                "New page; renders its content with client-side scripts",
            ),
        )
    return (
        "removed",
        "removed · interactive page",
        summary_card(
            old_c,
            "",
            "Removed page; had rendered its content with client-side scripts",
        ),
    )


def site_page(old_c, new_c, rel, link, images):
    """A page of ordinary content (prose, tables, figures, equations) as
    (state, label, body), or None when no reader would see a change: the
    engine's diff of the sanitized pages (diff-engine.py)."""
    if old_c is not None and new_c is not None:
        old_s, new_s = (
            (strip_volatile(old_c, rel), strip_volatile(new_c, rel))
            if _engine.names_files(new_c)
            else ("", "")
        )
        # A plot redrawn under its old name leaves the page's HTML as it was.
        redrawn = regenerated_images(old_s, new_s, images)
        # Spacing is no change, except in a code block.
        spaced = code_text(old_c) != code_text(new_c)
        if not redrawn and not spaced and _squash(old_c) == _squash(new_c):
            return None  # unchanged
        if (
            not redrawn
            and not spaced
            and markup_signature(old_c) == markup_signature(new_c)
        ):
            # Only non-visible markup changed (a Quarto cross-ref anchor, an
            # id/attribute edit): the rendered text is identical, so an inline
            # word diff would highlight nothing and embedding the whole page
            # reads as a dropped diff. Annotate + link instead.
            return (
                "changed",
                "changed · non-visible markup only (linked)",
                markup_only_summary(old_c, new_c, link),
            )
        body, changed = diff_content(
            old_s or strip_volatile(old_c, rel),
            new_s or strip_volatile(new_c, rel),
            images,
        )
        return ("changed", "changed", body) if changed else None
    if new_c is not None:
        return "new", "new page", strip_volatile(new_c, rel)
    return "removed", "removed", strip_volatile(old_c, rel)


class Output(NamedTuple):
    """One kind of output: one entry of OUTPUT_KINDS.

    name        what the header calls it
    recognised  how it is found, in words
    compare     its comparer
    found       for a page of the site: whether a page's content (old, new; None
                for a side that has none) is this kind, else None"""

    name: str
    recognised: str
    compare: Callable
    found: Callable | None = None


# The one table of outputs: what What changed can show a change of, and the
# comparer for each (the kinds of content inside a page are diff-engine.py's
# KINDS). A page is the first of the entries with `found` that finds it.
_OUTPUTS = (
    Output(
        "page made by script",
        "content made by running script: computed output (Plotly, widgets, "
        "notebook cells), or script that is most of the page",
        script_page,
        lambda *contents: any(is_self_contained(c) for c in contents if c is not None),
    ),
    Output(
        "site page",
        "any other rendered .html page of the site",
        site_page,
        lambda *contents: True,
    ),
    Output(
        "slide deck",
        "a page of reveal.js slides, matched slide by slide",
        slide_diff,
    ),
    Output(
        "LaTeX paper",
        "a folder paper-previews/<name>/ holding preview.json, built by the paper preview",
        paper_preview,
    ),
    Output(
        "data file",
        "text of a CSV, JSON, YAML or BibTeX file, which no site page shows: a "
        "caller that has both versions compares them",
        source_diff,
    ),
)
OUTPUT_KINDS = {output.name: output for output in _OUTPUTS}


def page_output(old_c, new_c):
    """The output kind of a page of the site, from its old and new content."""
    return next(o for o in _OUTPUTS if o.found and o.found(old_c, new_c))


def build(
    old_root,
    new_root,
    preview_url,
    title,
    out_path=None,
    theme_root=None,
    theme_url_prefix="",
    decks=None,
    reserved_local_output=False,
    old_source=None,
    new_source=None,
):
    sections = []
    toc = []
    images = SiteImages(old_root, new_root)
    # The project's own files at both commits, when the caller has them: each page
    # then offers its Source view.
    sources = SourceFiles(old_source, new_source) if old_source or new_source else None
    paper_root = os.path.join(new_root, "paper-previews")
    paper_dirs = []
    if os.path.isdir(paper_root):
        for directory, _, files in os.walk(paper_root):
            if "preview.json" in files:
                paper_dirs.append(
                    os.path.relpath(directory, paper_root).replace(os.sep, "/")
                )
    old_pages = list_pages(old_root, out_path, paper_dirs, reserved_local_output)
    new_pages = list_pages(new_root, out_path, paper_dirs, reserved_local_output)
    every_page = [*old_pages.items(), *new_pages.items()]
    theme_pages = (
        list_pages(theme_root, out_path, reserved_local_output=reserved_local_output)
        if theme_root
        else {}
    )
    # The name every page's title repeats, which a header's title leaves out.
    site = site_name(
        head_title(path, rel) for rel, path in [*every_page, *theme_pages.items()]
    )
    for paper_dir in sorted(paper_dirs, key=lambda name: (name != "paper", name)):
        paper_section = OUTPUT_KINDS["LaTeX paper"].compare(
            old_root, new_root, paper_dir
        )
        if paper_section:
            section, paper_status = paper_section
            sections.append(section)
            label, section_id = paper_identity(paper_dir)
            toc.append(
                TocEntry(
                    section_id,
                    html.unescape(label),
                    paper_status,
                    "" if paper_status == "changed" else paper_status,
                    paper_file(new_root, paper_dir),
                    "",
                )
            )
    slide_sections, slide_toc = [], []
    documents = {}
    for rel in sorted(set(old_pages) | set(new_pages)):

        def read(pages):
            if rel not in pages:
                return None
            # Invalid HTML encoding still has a usable text fallback. The live
            # deck reader stays strict and reports why frames cannot be built.
            with open(pages[rel], encoding="utf-8", errors="replace") as stream:
                return stream.read()

        old_doc, new_doc = read(old_pages), read(new_pages)
        documents[rel] = old_doc, new_doc
        old_slides, new_slides = reveal_slides(old_doc), reveal_slides(new_doc)
        # Format transitions need the ordinary page diff to retain both sides.
        if (old_doc is not None and old_slides is None) or (
            new_doc is not None and new_slides is None
        ):
            continue
        link = (
            (preview_url.rstrip("/") + "/" + quote(rel, safe="/"))
            if preview_url
            else quote(rel, safe="/")
        )
        result = OUTPUT_KINDS["slide deck"].compare(
            old_doc,
            new_doc,
            rel,
            link,
            old_slides,
            new_slides,
            decks,
            images,
            sources,
            site,
        )
        if result:
            section, entry = result
            slide_sections.append(section)
            slide_toc.append(entry)
        old_pages.pop(rel, None)
        new_pages.pop(rel, None)
    sections.extend(slide_sections)
    toc.extend(slide_toc)
    for rel in sorted(set(old_pages) | set(new_pages)):
        old_doc, new_doc = documents[rel]
        # The generated page lives inside the preview dir, so a bare relative
        # path deep-links to a sibling page without needing the absolute base.
        link = (preview_url.rstrip("/") + "/" + rel) if preview_url else rel
        old_c = normalize(extract_main(old_doc)) if old_doc is not None else None
        new_c = normalize(extract_main(new_doc)) if new_doc is not None else None
        output = page_output(old_c, new_c)
        result = output.compare(old_c, new_c, rel, link, images)
        source_only = False
        if result is None:
            # No reader would see a change; the page's source may still have one.
            result = unchanged_page(output, old_c, new_c, rel, link, sources)
            if result is None:
                continue
            source_only = True
        state, label, body = result
        title_txt = page_title(new_doc if new_doc is not None else old_doc, rel)
        detail = ""
        if state == "changed" and (n := count_changes(body)):
            detail = f"{n} change{'' if n == 1 else 's'}"
        aid = anchor_id(rel)
        if state != "removed":
            body = link_citations(body, link)
        state_class = "new" if state == "new" else state
        # A diff of the page's own content has the control, with every view; a new
        # or removed page, or a card that links to one, has the header alone.
        marked = state == "changed" and label == "changed"
        # (A page made by script has no views drawn from its versions: its scripts
        # are never carried. Its card is its one rendered side.)
        by_script = source_only and output.name == "page made by script"
        # (A page whose reader sees no change has no marks to match against.)
        found = sources.view(rel) if sources and marked else None
        source_file, source_html = source_part(found)
        if source_only:
            detail = SOURCE_ONLY
        head = diff_header(
            short_title(title_txt, site),
            link if state != "removed" else "",
            state_class,
            label,
            rel,
            views_control(
                ("marked",)
                + (() if by_script else ("clean", "before"))
                + (("source",) if found else ())
            )
            if marked
            else "",
            source_file,
            SOURCE_ONLY if source_only else "",
        )
        # Clean and Before / after are drawn from the two versions, each whole.
        versions = (
            version_templates(old_c, new_c, rel, link, images)
            if marked and not by_script
            else ""
        )
        sections.append(
            f'<section class="page-diff {state}" id="{aid}">\n{head}\n'
            f'<div class="diff-body">{body}</div>\n{versions}{source_html}</section>'
        )
        toc.append(
            TocEntry(
                aid,
                title_txt,
                state_class,
                "" if label == "changed" else label,
                rel,
                detail,
            )
        )

    if sections:
        n = len(sections)
        summary = f"{n} page{'s' if n != 1 else ''} changed"
        toc_html = overview([e._replace(title=short_title(e.title, site)) for e in toc])
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
        "<del>removed</del> words, the removed ones right before the added ones. "
        "A wholly added or removed block is shaded; a whole equation, figure or "
        "diagram is framed, the old in red, the new in green. "
        "Page titles link to the full preview.</p>"
    )
    escaped_title = html.escape(title)

    # A partial render holds only the changed pages, so the caller can name the
    # full site this page is served from as the theme source.
    template_doc, theme_css = None, None
    for root, pages in ((theme_root, theme_pages), (new_root, new_pages)):
        template_doc, depth = pick_template(pages)
        theme_css = extract_theme_css(template_doc, depth) if template_doc else None
        if theme_css:
            if root == new_root and theme_url_prefix:
                theme_css = prefix_theme_urls(theme_css, theme_url_prefix)
            break

    inner = (
        '<header class="diff-head"><h1>What changed</h1>'
        f"<p>{escaped_title} &middot; {summary}</p>{legend}</header>{toc_html}\n"
        f"{body_html}"
    )

    if theme_css:
        # Reuse the site theme, then wrap our content in Quarto's article
        # container so it inherits the real content width and typography.
        mode, follows_system = extract_default_mode(template_doc)
        theme_css = set_theme_mode(theme_css, mode)
        head = f"{theme_css}\n<style>{DIFF_STYLE}</style>"
        html_attrs = f' data-wc-mode="{mode}"'
        if follows_system:
            html_attrs += ' data-wc-follow-system="true"'
        body_attrs = f' class="quarto-{mode}"'
        mode_js = f"<script>{MODE_JS}</script>"
        body = (
            '<div class="page-columns page-rows-contents page-layout-article '
            'wc-scope">\n'
            '<main class="content" id="quarto-document-content">\n'
            f"{inner}\n</main>\n</div>"
        )
    else:
        head = f"<style>{PAGE_STYLE}{STANDALONE_STYLE}{DIFF_STYLE}</style>"
        body = f'<div class="wc-scope wc-standalone">{inner}</div>'
        html_attrs = body_attrs = mode_js = ""

    deck_assets = (
        decks.module.LIVE_STYLE + decks.module.LIVE_SCRIPT
        if decks and decks.used
        else ""
    )
    return (
        "<!doctype html>"
        f'<html lang="en"{html_attrs}><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{WHAT_CHANGED_META}"
        f"<title>What changed &middot; {escaped_title}</title>"
        f"{head}</head><body{body_attrs}>{mode_js}{body}"
        f"<script>{FOLD_JS}</script><script>{PAPER_JS}</script>"
        f"<script>{VIEWS_JS}</script>"
        f"{pair_script(body_html)}"
        f"{math_script(body_html)}"
        f"{mermaid_script(body_html)}"
        f"{deck_assets}</body></html>"
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
    ap.add_argument(
        "--theme-root",
        help="rendered full site to borrow the theme from (default: --new)",
    )
    ap.add_argument(
        "--theme-url-prefix",
        default="",
        help="served asset prefix when the theme comes from --new",
    )
    ap.add_argument(
        "--render-decks",
        metavar="DIR",
        help="publish marked live decks into generated DIR (needs deck-review.py"
        "; else slides as text); existing DIR contents are replaced",
    )
    ap.add_argument(
        "--old-source",
        metavar="DIR",
        help="the project's own files (.qmd, .md, .ipynb) as of --old, so that each "
        "page can show its source",
    )
    ap.add_argument(
        "--new-source",
        metavar="DIR",
        help="the project's own files as of --new",
    )
    ap.add_argument(
        "--reserved-local-output",
        action="store_true",
        help="exclude root what-changed.html and what-changed-assets/ (local Make target)",
    )
    ap.add_argument(
        "--render-decks-url",
        metavar="URL",
        help="URL of --render-decks as served beside --out (default: its path relative to --out)",
    )
    args = ap.parse_args(argv)
    decks = None
    if args.render_decks:
        # Never recursively delete outside the candidate site or through a symlink.
        site_path = os.path.abspath(args.new)
        image_path = os.path.abspath(args.render_decks)
        site_root, image_root = (
            os.path.realpath(site_path),
            os.path.realpath(image_path),
        )
        try:
            unsafe = (
                image_root == site_root
                or os.path.commonpath([site_root, image_root]) != site_root
                or os.path.commonpath([site_path, image_path]) != site_path
                or os.path.commonpath([image_root, os.path.realpath(args.out)])
                == image_root
                or os.path.commonpath([image_root, os.path.realpath(args.old)])
                == image_root
            )
        except ValueError:
            unsafe = True
        if unsafe:
            ap.error(
                "--render-decks must be a separate generated directory inside the new site"
            )
        component = image_path
        while component != site_path:
            if os.path.islink(component):
                ap.error("--render-decks must not contain symlinks")
            component = os.path.dirname(component)
        shutil.rmtree(image_root, ignore_errors=True)
        module = load_deck_review()
        if module:
            decks = DeckRenderer(
                module,
                args.old,
                args.new,
                args.render_decks,
                args.render_decks_url
                or quote(
                    os.path.relpath(
                        args.render_decks, os.path.dirname(os.path.abspath(args.out))
                    ).replace(os.sep, "/"),
                    safe="/",
                ),
            )
    try:
        doc = build(
            args.old,
            args.new,
            args.preview_url,
            args.title,
            out_path=args.out,
            theme_root=args.theme_root,
            theme_url_prefix=args.theme_url_prefix,
            decks=decks,
            reserved_local_output=args.reserved_local_output,
            old_source=args.old_source,
            new_source=args.new_source,
        )
    finally:
        if decks:
            decks.close()
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"wrote {args.out} ({len(doc)} bytes)", file=sys.stderr)


if __name__ == "__main__":
    main()
