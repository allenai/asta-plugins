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


def emit_run(tokens, wrapper):
    """Render a changed run.

    wrapper is 'ins' or 'del'. Structural tags close/skip the wrapper so the
    result stays well-formed:
      * ins: structural tags are emitted verbatim (outside the wrapper); words
        and inline tags are highlighted inside <ins>.
      * del: a fully-deleted subtree's structural tags are dropped (open+close
        both fall in the deleted run, so nesting stays balanced); deleted words
        and inline tags are shown struck-through inside <del>.
    """
    out = []
    open_wrap = False

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

    for kind, text in tokens:
        if kind == "tag" and not is_inline_tag(text):
            close()
            if wrapper == "ins":
                out.append(text)  # keep structure for inserted blocks
            # deleted structural tags are dropped with their subtree
        elif kind == "space":
            # ride whitespace inside an open wrapper, else emit bare
            (out.append(text) if not open_wrap else out.append(text))
        else:  # word or inline tag
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


PAGE_STYLE = """
:root { color-scheme: light dark; }
body { font: 15px/1.6 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
       margin: 0; padding: 0 1.5rem 4rem; max-width: 60rem; margin-inline: auto;
       color: #1b1b1b; }
header.diff-head { padding: 1.5rem 0 0.5rem; }
header.diff-head h1 { margin: 0 0 .25rem; font-size: 1.5rem; }
header.diff-head p { margin: .25rem 0; color: #555; }
.legend { font-size: .85rem; color: #555; }
.legend ins, .legend del { padding: 0 .2em; }
.empty { color: #555; font-style: italic; }
nav.toc { font-size: .9rem; margin: 1rem 0 2rem; }
nav.toc a { display: inline-block; margin-right: 1rem; }
section.page-diff { border-top: 3px solid #0f6cbd; margin-top: 2.5rem;
                    padding-top: .5rem; }
section.page-diff.new { border-top-color: #107c10; }
section.page-diff.removed { border-top-color: #d13438; }
section.page-diff > h2 { font-size: 1.15rem; }
section.page-diff > h2 .tag { font-size: .7em; font-weight: 600; padding: .1em .5em;
    border-radius: 1em; vertical-align: middle; margin-left: .5em; }
.tag.changed { background: #0f6cbd; color: #fff; }
.tag.new { background: #107c10; color: #fff; }
.tag.removed { background: #d13438; color: #fff; }
.diff-body { overflow-wrap: break-word; }
.diff-body table { border-collapse: collapse; }
.diff-body td, .diff-body th { border: 1px solid #ccc; padding: .3em .5em; }
ins { background: #d4f7d4; text-decoration: none; box-shadow: 0 0 0 1px #a3e0a3; }
del { background: #ffd7d5; text-decoration: line-through; box-shadow: 0 0 0 1px #f1b0ad; }
ins img, del img { outline: 3px solid; }
ins img { outline-color: #107c10; }
del img { outline-color: #d13438; opacity: .6; }
@media (prefers-color-scheme: dark) {
  body { background: #1b1b1b; color: #e6e6e6; }
  header.diff-head p, .legend, .empty { color: #aaa; }
  ins { background: #133a13; box-shadow: 0 0 0 1px #2a5a2a; }
  del { background: #4a1513; box-shadow: 0 0 0 1px #7a2a27; }
  .diff-body td, .diff-body th { border-color: #444; }
}
"""


def page_title(doc, rel):
    m = re.search(r"(?is)<title>(.*?)</title>", doc)
    if m:
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        if t:
            return t
    return rel


def anchor_id(rel):
    return "p-" + re.sub(r"[^a-zA-Z0-9]+", "-", rel).strip("-")


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
        if new_doc is not None and old_doc is not None:
            old_c = normalize(extract_main(old_doc))
            new_c = normalize(extract_main(new_doc))
            if re.sub(r"\s+", " ", old_c).strip() == re.sub(r"\s+", " ", new_c).strip():
                continue  # unchanged
            body, changed = diff_content(old_c, new_c)
            if not changed:
                continue
            state, label = "changed", "changed"
            title_txt = page_title(new_doc, rel)
        elif new_doc is not None:
            state, label = "new", "new page"
            body = extract_main(new_doc)
            title_txt = page_title(new_doc, rel)
        else:
            state, label = "removed", "removed"
            body = normalize(extract_main(old_doc))
            title_txt = page_title(old_doc, rel)
        aid = anchor_id(rel)
        # The generated page lives inside the preview dir, so a bare relative
        # path deep-links to a sibling page without needing the absolute base.
        link = (preview_url.rstrip("/") + "/" + rel) if preview_url else rel
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
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>What changed &middot; {escaped_title}</title>"
        f"<style>{PAGE_STYLE}</style></head><body>"
        '<header class="diff-head"><h1>What changed</h1>'
        f"<p>{escaped_title} &middot; {summary}</p>{legend}</header>{toc_html}\n"
        f"{body_html}</body></html>"
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
