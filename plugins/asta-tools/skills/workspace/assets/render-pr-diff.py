#!/usr/bin/env python3
"""Generate a rendered visual diff of a Quarto site's PR preview vs. its base.

Given a base rendered site (main, already published to the gh-pages root) and a
head rendered site (this PR's `_site`), this walks every content page, extracts
each page's main content region, and word-diffs it. Pages whose content differs
get a section on a single self-contained `changes` page with insertions and
deletions highlighted inline — so a reviewer clicks one link and sees *what*
changed *where*, instead of hunting through the Quarto site root.

It is intentionally dependency-light (only `lxml`) and site-agnostic: it keys
off the Quarto `<main>` content region and degrades gracefully when a page is
new, removed, or unparseable. It writes the changes page and prints, to stdout,
a JSON list of changed pages (relative html path + human title) so the caller
can build deep links in the PR comment.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from lxml import html as lxml_html
from lxml.html.diff import htmldiff

# Content selectors tried in order. Quarto renders the article body inside
# <main>; falling back to the whole <body> keeps this working on non-Quarto
# HTML too. The document chrome (nav, sidebar, footer) is deliberately excluded
# so identical navigation across pages never registers as a change.
CONTENT_XPATHS = (
    '//main[@id="quarto-document-content"]',
    '//main',
    '//div[@id="quarto-content"]',
    '//body',
)

# Class fragments whose elements are stripped from the content before diffing.
# `quarto-title-meta` holds the auto "Modified: <date>" stamp (from
# `date-modified: last-modified`), which otherwise flags every page as changed
# on every build. This is pure build boilerplate, not survey content.
STRIP_CLASS_FRAGMENTS = ("quarto-title-meta",)


def extract_content(path: str) -> tuple[str, str] | None:
    """Return (inner_html, title) for a page, or None if it can't be read."""
    try:
        with open(path, "rb") as fh:
            doc = lxml_html.fromstring(fh.read())
    except (OSError, ValueError, lxml_html.etree.ParserError):
        return None
    node = None
    for xp in CONTENT_XPATHS:
        found = doc.xpath(xp)
        if found:
            node = found[0]
            break
    if node is None:
        return None
    for frag in STRIP_CLASS_FRAGMENTS:
        for junk in node.xpath(f'.//*[contains(@class, "{frag}")]'):
            junk.getparent().remove(junk)
    title_nodes = doc.xpath("//title/text()")
    title = title_nodes[0].strip() if title_nodes else ""
    # Serialize children only; the wrapper tag itself is not part of the content.
    inner = (node.text or "") + "".join(
        lxml_html.tostring(c, encoding="unicode") for c in node
    )
    return inner, title


def iter_pages(root: str):
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".html"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            yield rel, full


PAGE_CSS = """
:root { color-scheme: light dark; }
body { font: 15px/1.6 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
       margin: 0; padding: 0 1.5rem 4rem; max-width: 60rem; margin-inline: auto;
       color: #1b1b1b; }
header.diff-head { padding: 1.5rem 0 0.5rem; }
header.diff-head h1 { margin: 0 0 .25rem; font-size: 1.5rem; }
header.diff-head p { margin: .25rem 0; color: #555; }
.legend { font-size: .85rem; color: #555; }
.legend ins, .legend del { padding: 0 .2em; }
section.page-diff { border-top: 3px solid #0f6cbd; margin-top: 2.5rem;
                    padding-top: .5rem; }
section.page-diff.new { border-top-color: #107c10; }
section.page-diff > h2 { font-size: 1.15rem; }
section.page-diff > h2 .tag { font-size: .7em; font-weight: 600; padding: .1em .5em;
    border-radius: 1em; vertical-align: middle; margin-left: .5em; }
.tag.changed { background: #0f6cbd; color: #fff; }
.tag.new { background: #107c10; color: #fff; }
ins { background: #d4f7d4; text-decoration: none; box-shadow: 0 0 0 1px #a3e0a3; }
del { background: #ffd7d5; text-decoration: line-through; box-shadow: 0 0 0 1px #f1b0ad; }
ins img, del img { outline: 3px solid; }
ins img { outline-color: #107c10; }
del img { outline-color: #d13438; opacity: .6; }
.diff-body { overflow-wrap: break-word; }
.diff-body table { border-collapse: collapse; }
.diff-body td, .diff-body th { border: 1px solid #ccc; padding: .3em .5em; }
@media (prefers-color-scheme: dark) {
  body { background: #1b1b1b; color: #e6e6e6; }
  header.diff-head p, .legend { color: #aaa; }
  ins { background: #133a13; box-shadow: 0 0 0 1px #2a5a2a; }
  del { background: #4a1513; box-shadow: 0 0 0 1px #7a2a27; }
}
"""


def slug(rel: str) -> str:
    return "p-" + "".join(c if c.isalnum() else "-" for c in rel).strip("-")


def build_changes_page(changed, preview_base: str, pr_number: str, repo: str) -> str:
    legend = (
        '<p class="legend">Highlighted below: <ins>added / changed text</ins> '
        "and <del>removed text</del>. Each section links to the full rendered "
        "page in this PR's preview.</p>"
    )
    head = (
        '<header class="diff-head">'
        f"<h1>What changed in this preview</h1>"
        f"<p>{len(changed)} page(s) changed in "
        f'<a href="https://github.com/{repo}/pull/{pr_number}">PR #{pr_number}</a>, '
        "vs. the current site. Navigation and unchanged pages are omitted.</p>"
        f"{legend}</header>"
    )
    sections = []
    for rel, title, diff_html, is_new in changed:
        preview_url = preview_base.rstrip("/") + "/" + rel
        label = title or rel
        tag = (
            '<span class="tag new">new page</span>'
            if is_new
            else '<span class="tag changed">changed</span>'
        )
        cls = "page-diff new" if is_new else "page-diff"
        sections.append(
            f'<section class="{cls}" id="{slug(rel)}">'
            f'<h2><a href="{preview_url}">{label}</a>{tag}</h2>'
            f'<div class="diff-body">{diff_html}</div>'
            "</section>"
        )
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>What changed &middot; PR preview diff</title>"
        f"<style>{PAGE_CSS}</style></head><body>"
        f"{head}{''.join(sections)}</body></html>"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-dir", required=True, help="rendered base site (main)")
    ap.add_argument("--head-dir", required=True, help="rendered head site (this PR)")
    ap.add_argument("--out", required=True, help="path to write the changes page")
    ap.add_argument(
        "--preview-base",
        default=".",
        help="URL/path of the PR preview root that the changes page lives in; "
        "defaults to '.' so links stay relative and resolve on any served domain",
    )
    ap.add_argument("--pr-number", default="")
    ap.add_argument("--repo", default="")
    args = ap.parse_args()

    changed = []
    for rel, full in sorted(iter_pages(args.head_dir)):
        if os.path.basename(rel) == "changes.html":
            continue
        head = extract_content(full)
        if head is None:
            continue
        head_html, head_title = head
        base_path = os.path.join(args.base_dir, rel)
        base = extract_content(base_path) if os.path.exists(base_path) else None
        is_new = base is None
        if is_new:
            diff_html = htmldiff("", head_html)
        else:
            base_html, _ = base
            if base_html.strip() == head_html.strip():
                continue
            diff_html = htmldiff(base_html, head_html)
            # If nothing survived as an ins/del marker the pages differ only in
            # boilerplate (e.g. build timestamp) — don't report them as changed.
            if "<ins>" not in diff_html and "<del>" not in diff_html:
                continue
        changed.append((rel, head_title, diff_html, is_new))

    page = build_changes_page(changed, args.preview_base, args.pr_number, args.repo)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)

    manifest = [
        {"path": rel, "title": title or rel, "new": is_new, "anchor": slug(rel)}
        for rel, title, _diff, is_new in changed
    ]
    json.dump(manifest, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
