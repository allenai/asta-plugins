"""Tests for the rendered Quarto preview diff generator."""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


def _underline_contexts(css):
    """Selector text preceding every `text-decoration: underline` in the output.

    CSS comments (which document the rules and quote CSS verbatim) are stripped
    first so prose about underlines isn't mistaken for an actual rule.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return re.findall(r"([^{}]*)\{[^{}]*text-decoration:\s*underline", css)


def _only_underline_on_hover(css):
    """No resting underline anywhere — underline is only ever a :hover/:focus cue."""
    return all(
        all(":hover" in selector or ":focus" in selector for selector in ctx.split(","))
        for ctx in _underline_contexts(css)
    )


SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/asta-tools/skills/workspace/assets/what-changed.py"
)
SPEC = importlib.util.spec_from_file_location("what_changed", SCRIPT)
WHAT_CHANGED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WHAT_CHANGED)


def test_paper_diff_appears_before_quarto_changes(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    (new / "paper-previews/paper").mkdir(parents=True)
    (new / "paper-previews/paper/preview.json").write_text(
        json.dumps({"changed": True, "diff": True})
    )
    (new / "index.html").write_text("<main><p>New Quarto page</p></main>")

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert result.index('id="paper-diff"') < result.index('id="p-index-html"')
    assert (
        'data="paper-previews/paper/what-changed.pdf#navpanes=0&amp;view=FitH"'
        in result
    )


def test_multiple_papers_have_distinct_diff_sections(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    for name in ("paper", "latex"):
        directory = new / "paper-previews" / name
        directory.mkdir(parents=True)
        (directory / "preview.json").write_text(
            json.dumps({"changed": True, "diff": False})
        )
        (directory / "main.pdf").write_bytes(b"pdf")

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert 'id="paper-diff"' in result
    assert 'id="paper-diff-6c61746578"' in result
    assert 'href="paper-previews/latex/main.pdf"' in result
    assert 'href="#paper-diff-6c61746578"' in result
    assert "<iframe" not in result


def test_paper_section_ids_distinguish_dash_from_path_separator(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    for name in ("foo-bar", "foo/bar"):
        directory = new / "paper-previews" / name
        directory.mkdir(parents=True)
        (directory / "preview.json").write_text(
            json.dumps({"changed": True, "new": True})
        )

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    for section_id in ("paper-diff-666f6f2d626172", "paper-diff-666f6f2f626172"):
        assert result.count(f'id="{section_id}"') == 1
        assert result.count(f'href="#{section_id}"') == 1


def test_paper_directory_is_encoded_in_links_and_escaped_in_attributes(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    name = 'draft &" #1'
    directory = new / "paper-previews" / name
    directory.mkdir(parents=True)
    (directory / "preview.json").write_text(
        json.dumps({"changed": True, "diff": False})
    )

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert 'href="paper-previews/draft%20%26%22%20%231/main.pdf"' in result
    assert "Draft &amp;&quot; #1" in result
    assert 'href="draft &"' not in result


def test_nested_paper_appears_with_source_path(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    directory = new / "paper-previews/lit-review/latex"
    directory.mkdir(parents=True)
    (directory / "preview.json").write_text(json.dumps({"changed": True, "new": True}))
    (directory / "main.pdf").write_bytes(b"pdf")

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert "Lit Review / LaTeX" in result
    assert 'href="paper-previews/lit-review/latex/main.pdf"' in result


def test_site_section_with_main_pdf_remains_in_what_changed(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    for root, body in ((old, "old"), (new, "new")):
        (root / "docs").mkdir(parents=True)
        (root / "docs/main.pdf").write_bytes(b"pdf")
        (root / "docs/index.html").write_text(f"<main><p>{body}</p></main>")

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert 'id="p-docs-index-html"' in result
    assert "new" in result


def test_paper_preview_does_not_hide_quarto_section_with_same_name(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    for root, body in ((old, "old"), (new, "new")):
        (root / "latex").mkdir(parents=True)
        (root / "latex/index.html").write_text(f"<main><p>{body}</p></main>")
    paper = new / "paper-previews/latex"
    paper.mkdir(parents=True)
    (paper / "preview.json").write_text(json.dumps({"changed": True, "diff": False}))

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert 'id="p-latex-index-html"' in result
    assert 'id="paper-diff-6c61746578"' in result


def test_removed_second_paper_has_its_own_notice(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    (new / "paper-previews/latex").mkdir(parents=True)
    (new / "paper-previews/latex/preview.json").write_text(
        json.dumps({"changed": True, "removed": True})
    )

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert 'id="paper-diff-6c61746578"' in result
    assert "LaTeX" in result
    assert 'href="paper-previews/latex/main.pdf"' not in result


def test_paper_diff_reads_in_the_paper_pages_viewer(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    (new / "paper-previews/paper").mkdir(parents=True)
    (new / "paper-previews/paper/preview.json").write_text(
        json.dumps({"changed": True, "diff": True})
    )
    # Thumbnails an older preview left behind are no longer shown.
    (new / "paper-previews/paper/diff-page-1.png").write_bytes(b"png")

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert 'class="paper-view"' in result
    assert 'class="paper-expand"' in result
    assert (
        'data-pdf="paper-previews/paper/what-changed.pdf" aria-pressed="true">'
        "This PR's changes marked</button>"
    ) in result
    assert (
        'data-pdf="paper-previews/paper/main.pdf" aria-pressed="false">Clean</button>'
    ) in result
    assert "diff-page-1.png" not in result
    assert 'event.key === "Escape"' in result


def test_paper_without_a_diff_shows_the_clean_pdf_and_no_switch(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    (new / "paper-previews/paper").mkdir(parents=True)
    (new / "paper-previews/paper/preview.json").write_text(
        json.dumps({"changed": True, "diff": False})
    )

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert 'data="paper-previews/paper/main.pdf#navpanes=0&amp;view=FitH"' in result
    assert 'class="paper-modes"' not in result


def test_non_tex_paper_inputs_link_current_pdf_without_highlight_claim(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    (new / "paper-previews/paper").mkdir(parents=True)
    (new / "paper-previews/paper/preview.json").write_text(
        json.dumps({"changed": True, "diff": False, "other_inputs": True})
    )

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert "current PDF is available without highlights" in result
    assert 'href="paper-previews/paper/main.pdf"' in result


def test_unmarked_latex_change_links_current_pdf_without_highlight_claim(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    (new / "paper-previews/paper").mkdir(parents=True)
    (new / "paper-previews/paper/preview.json").write_text(
        json.dumps({"changed": True, "diff": False, "unhighlighted": True})
    )

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert "diff has no marked text" in result
    assert 'href="paper-previews/paper/main.pdf"' in result
    assert 'href="paper-previews/paper/what-changed.pdf"' not in result


def test_paper_diff_fallback_links_current_pdf(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    (new / "paper-previews/paper").mkdir(parents=True)
    (new / "paper-previews/paper/preview.json").write_text(
        json.dumps({"changed": True, "diff": False})
    )

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert 'href="paper-previews/paper/main.pdf"' in result
    assert 'href="paper-previews/paper/what-changed.pdf"' not in result


def test_new_paper_is_labeled_as_added(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    (new / "paper-previews/paper").mkdir(parents=True)
    (new / "paper-previews/paper/preview.json").write_text(
        json.dumps({"changed": True, "diff": False, "new": True})
    )

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert "Paper added" in result
    assert 'class="page-diff new"' in result
    assert 'href="paper-previews/paper/main.pdf"' in result
    assert "The LaTeX diff could not be built" not in result


def test_removed_paper_has_notice_without_broken_pdf_link(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    (new / "paper-previews/paper").mkdir(parents=True)
    (new / "paper-previews/paper/preview.json").write_text(
        json.dumps({"changed": True, "removed": True})
    )
    (new / "index.html").write_text("<main><p>Quarto remains available</p></main>")

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert "Paper removed" in result
    assert 'class="page-diff removed"' in result
    assert 'href="#paper-diff">Paper <span class="tag removed">' in result
    assert 'href="paper-previews/paper/main.pdf"' not in result
    assert 'id="p-index-html"' in result


def test_invalid_paper_manifest_keeps_quarto_changes(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    (new / "paper-previews/paper").mkdir(parents=True)
    (new / "paper-previews/paper/preview.json").write_text("{invalid")
    (new / "index.html").write_text("<main><p>New Quarto page</p></main>")

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert 'id="p-index-html"' in result
    assert 'id="paper-diff"' not in result


def test_build_reuses_quarto_theme_and_marks_changes_accessibly(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = """<!doctype html><html><head>
      <link href="site_libs/bootstrap/bootstrap.min.css" rel="stylesheet">
      <style>.quarto-title {{ font-weight: 700; }}</style>
      </head><body><main><p>{text}</p></main></body></html>"""
    (old / "index.html").write_text(shell.format(text="Old text"))
    (new / "index.html").write_text(shell.format(text="New text"))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert 'href="site_libs/bootstrap/bootstrap.min.css"' in result
    assert ".quarto-title { font-weight: 700; }" in result
    assert (
        'class="page-columns page-rows-contents page-layout-article wc-scope"' in result
    )
    assert "<del>Old</del>" in result
    assert "<ins>New</ins>" in result
    # Insertions are background-only (no underline); deletions keep strikethrough.
    # The only `text-decoration: underline` allowed is the :hover/:focus link
    # affordance — never a resting underline on insertions or links.
    underline_contexts = _underline_contexts(result)
    assert underline_contexts
    assert _only_underline_on_hover(result), underline_contexts
    assert "border-inline-start: 2px solid var(--wc-ins-line)" in result
    assert "text-decoration: line-through" in result
    assert "--wc-tag-fg: #fff" in result
    assert ".wc-scope nav.toc .tag" in result
    assert (
        ".wc-scope .tag.changed { background: var(--wc-changed); "
        "color: var(--wc-tag-fg); }" in result
    )


def test_evidence_claim_underline_is_legible_on_the_diff(tmp_path):
    """Evidence gets a perceptible dotted rule without restoring insertion lines.

    The extension's default 1px, 32%-opacity border is too subtle against the
    diff's green insertion tint, so the generator strengthens that one cue with
    a theme-aware rule. The claim itself must also survive the word-diff
    intact.
    """
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "index.html").write_text(
        "<html><head></head><body><main><p>Baseline.</p></main></body></html>"
    )
    # The evidence extension injects its `.ev` styling into the page <head>; the
    # diff reuses the template page's head styles, so it must carry through.
    (new / "index.html").write_text(
        "<html><head><style>.ev { border-bottom: 1px dotted rgba(0, 0, 0, 0.32); }"
        "</style></head><body><main>"
        '<p>NatureBench has <span class="ev" title="evidence">90 tasks</span>.</p>'
        "</main></body></html>"
    )

    result = WHAT_CHANGED.build(old, new, "", "PR #2")

    # No old amber highlight or resting insertion/link underline competes with the
    # evidence cue. The diff strengthens only the evidence claim's dotted rule.
    assert "--wc-ev-bg" not in result
    assert "box-shadow: inset 0 -2px 0" not in result
    underline_contexts = _underline_contexts(result)
    assert underline_contexts
    assert _only_underline_on_hover(result), underline_contexts
    assert (
        ".wc-scope .ev { border-bottom: 2px dotted var(--bs-link-color, var(--wc-changed)); }"
        in result
    )
    assert "#2a88ef" not in result
    # The extension's own `.ev` styling still survives via the reused head CSS.
    assert ".ev { border-bottom: 1px dotted rgba(0, 0, 0, 0.32); }" in result
    # The claim survives the word-diff with its class intact.
    assert 'class="ev"' in result
    assert "90 tasks" in result


def test_links_are_not_underlined_at_rest_on_the_diff(tmp_path):
    """The reused theme carries Bootstrap's default `a { text-decoration: underline }`.
    On the diff that underlines every citation, crossref (e.g. "Table 1") and bare
    URL, and inside an inserted run those links take the green ins colour — reading
    as green underlines scattered across the page. The generator suppresses the
    resting link underline (GitHub's diff view does the same) so the dotted `.ev`
    cue is the only resting underline; the underline returns on hover/focus."""
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "index.html").write_text(
        "<html><head></head><body><main><p>Baseline.</p></main></body></html>"
    )
    (new / "index.html").write_text(
        "<html><head></head><body><main>"
        '<p>See <a href="#tbl-x">Table 1</a> and '
        '<a href="https://arxiv.org/abs/1">the paper</a>.</p>'
        "</main></body></html>"
    )

    result = WHAT_CHANGED.build(old, new, "", "PR #3")

    # Resting link underline is suppressed, restored only on hover/focus.
    assert ".wc-scope a { text-decoration: none; font-weight: 600; }" in result
    assert (
        ".wc-scope a:hover, .wc-scope a:focus { text-decoration: underline; }" in result
    )
    underline_contexts = _underline_contexts(result)
    assert underline_contexts
    assert _only_underline_on_hover(result), underline_contexts
    # The links themselves still render (identifiable by colour), just not underlined.
    assert 'href="#tbl-x"' in result


def test_nested_template_stylesheet_is_rebased_to_preview_root(tmp_path):
    new = tmp_path / "new"
    new.mkdir()
    nested = new / "guide"
    nested.mkdir()
    (nested / "page.html").write_text(
        '<html><head><link rel="stylesheet" href="../site_libs/theme.css">'
        "</head><body><main>Content</main></body></html>"
    )

    doc, depth = WHAT_CHANGED.pick_template(WHAT_CHANGED.list_pages(new))
    theme = WHAT_CHANGED.extract_theme_css(doc, depth)

    assert depth == 1
    assert 'href="site_libs/theme.css"' in theme


def test_template_skips_slide_deck_for_a_site_page(tmp_path):
    new = tmp_path / "new"
    (new / "talk").mkdir(parents=True)
    (new / "a-deck.html").write_text(
        '<html><head><link rel="stylesheet" href="site_libs/revealjs/reveal.css">'
        '</head><body><div class="reveal slides-ready">Deck</div></body></html>'
    )
    (new / "talk/page.html").write_text(
        '<html><head><link rel="stylesheet" href="../site_libs/theme.css">'
        '</head><body><main class="reveal">Content</main></body></html>'
    )

    doc, depth = WHAT_CHANGED.pick_template(WHAT_CHANGED.list_pages(new))

    assert depth == 1
    assert "theme.css" in doc


def test_partial_render_borrows_theme_from_full_site(tmp_path):
    old, new, site = tmp_path / "old", tmp_path / "new", tmp_path / "site"
    for root in (old, new, site):
        (root / "talk").mkdir(parents=True)
    deck = (
        '<html><head><link rel="stylesheet" href="../site_libs/revealjs/reveal.css">'
        '</head><body><div class="reveal"><section><p>{}</p></section></div></body></html>'
    )
    (old / "talk/slides.html").write_text(deck.format("Old finding"))
    (new / "talk/slides.html").write_text(deck.format("New finding"))
    (site / "index.html").write_text(
        '<html><head><link href="site_libs/bootstrap/bootstrap.min.css" '
        'rel="stylesheet"></head><body><main>Site</main></body></html>'
    )
    out = site / "what-changed.html"
    out.write_text("<html><head><style>.stale {}</style></head></html>")

    result = WHAT_CHANGED.build(old, new, "", "Local", out_path=out, theme_root=site)

    assert 'href="site_libs/bootstrap/bootstrap.min.css"' in result
    assert "reveal.css" not in result
    assert ".stale" not in result
    # Without a themed full site, the changed pages remain the fallback source.
    fallback = WHAT_CHANGED.build(old, new, "", "Local", theme_root=tmp_path / "none")
    assert 'href="site_libs/revealjs/reveal.css"' in fallback


@pytest.mark.parametrize("separate_theme_root", [False, True])
def test_template_search_continues_after_unstyled_pages(tmp_path, separate_theme_root):
    old, new, site = tmp_path / "old", tmp_path / "new", tmp_path / "site"
    for root in (old, new, site):
        root.mkdir()
    (new / "deck.html").write_text(
        '<head><link rel="stylesheet" href="site_libs/revealjs/reveal.css"></head>'
        '<body><div class="reveal"><section>New finding</section></div></body>'
    )
    theme_root = site if separate_theme_root else new
    (theme_root / "index.html").write_text("<head></head><main>Unstyled index</main>")
    (theme_root / "guide").mkdir()
    (theme_root / "guide/themed.html").write_text(
        '<head><link rel="stylesheet" href="../site_libs/site.css" '
        'id="quarto-bootstrap" data-mode="dark"></head>'
        '<body class="quarto-dark"><main>Styled site page</main></body>'
    )

    result = WHAT_CHANGED.build(
        old,
        new,
        "",
        "Local comparison",
        theme_root=site if separate_theme_root else None,
        theme_url_prefix="what-changed-assets/",
    )

    prefix = "" if separate_theme_root else "what-changed-assets/"
    assert f'href="{prefix}site_libs/site.css"' in result
    assert "reveal.css" not in result
    assert 'data-wc-mode="dark"' in result


@pytest.mark.parametrize("legacy", [False, True])
def test_previous_comparison_cannot_supply_the_partial_render_theme(tmp_path, legacy):
    old, new, site = tmp_path / "old", tmp_path / "new", tmp_path / "site"
    for root in (old, new, site):
        root.mkdir()
    (new / "index.html").write_text(
        "<head><style>.stale-comparison { color: red; }/*"
        + "old theme " * 1000
        + "*/</style></head>"
        "<main>A changed finding</main>"
    )
    previous = WHAT_CHANGED.build(old, new, "", "Previous comparison")
    if legacy:
        previous = previous.replace(WHAT_CHANGED.WHAT_CHANGED_META, "")
        # Legacy output has no marker, and its wrapper lies beyond the prefix
        # read during page discovery. The reserved root name must exclude it.
        assert not WHAT_CHANGED.is_what_changed_artifact(previous[:4096])
    (site / "what-changed.html").write_text(previous)
    # No index page: the prior report sorts before the real theme source.
    (site / "z-page.html").write_text(
        '<head><link href="site_libs/site-theme.css" rel="stylesheet"></head>'
        "<main>The real site</main>"
    )
    result = WHAT_CHANGED.build(
        old,
        new,
        "",
        "Local comparison",
        out_path=tmp_path / "temporary/what-changed.html",
        theme_root=site,
        reserved_local_output=True,
    )
    assert 'href="site_libs/site-theme.css"' in result
    assert ".stale-comparison" not in result


def test_dark_quarto_theme_selects_dark_diff_palette(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = """<html><head><link id="quarto-bootstrap" data-mode="dark"
      rel="stylesheet" href="site_libs/bootstrap.css"></head>
      <body><main><p>{text}</p></main></body></html>"""
    (old / "index.html").write_text(shell.format(text="Old"))
    (new / "index.html").write_text(shell.format(text="New"))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert 'data-wc-mode="dark"' in result
    assert '[data-wc-mode="dark"] .wc-scope' in result
    assert "--wc-tag-fg: #0d1117" in result


def test_dark_default_site_starts_dark_and_follows_the_stored_toggle(tmp_path):
    # Quarto renders the light sheet first and picks dark only in the browser.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = """<html><head>
      <link href="site_libs/bootstrap.min.css" rel="stylesheet"
        class="quarto-color-scheme" id="quarto-bootstrap" data-mode="light">
      <link href="site_libs/bootstrap-dark.min.css" rel="prefetch"
        class="quarto-color-scheme quarto-color-alternate" id="quarto-bootstrap"
        data-mode="dark">
      <script>const authorPrefersDark = true;
        const darkModeDefault = authorPrefersDark;</script>
      </head><body><main><p>{text}</p></main></body></html>"""
    (old / "index.html").write_text(shell.format(text="Old"))
    (new / "index.html").write_text(shell.format(text="New"))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert '<html lang="en" data-wc-mode="dark">' in result
    assert '<body class="quarto-dark">' in result
    assert re.search(
        r'<link rel="stylesheet" href="site_libs/bootstrap.min.css"', result
    )
    assert re.search(
        r'<link rel="stylesheet" href="site_libs/bootstrap-dark.min.css"', result
    )
    # The reader's toggle (Quarto's sentinel) still wins in the browser.
    assert 'localStorage.getItem("quarto-color-scheme")' in result
    assert "data-wc-follow-system" not in result


def test_output_ships_client_side_folding_but_keeps_full_content(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    filler = "".join(
        f"<p>Untouched paragraph number {i} with enough words to matter.</p>"
        for i in range(8)
    )
    shell = "<html><head></head><body><main>{body}</main></body></html>"
    (old / "index.html").write_text(shell.format(body=filler + "<p>original line</p>"))
    (new / "index.html").write_text(shell.format(body=filler + "<p>replaced line</p>"))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    # The folding is progressive enhancement: the script ships and the styling
    # for the collapsed hunks is present.
    assert "details.wc-fold" in result
    assert "Expand all unchanged" in result
    assert "DOMContentLoaded" in result
    # A single rendered element can hold a whole section, so long singleton
    # blocks and oversized neighboring context are folded by default.
    assert "var MIN_BLOCKS = 1" in result
    assert "var MAX_CONTEXT_CHARS = 500" in result
    assert "kids[j].textContent.length <= MAX_CONTEXT_CHARS" in result
    # ...but the server never pre-collapses, so no-JS reviewers still get
    # every unchanged paragraph verbatim.
    assert "Untouched paragraph number 7" in result
    # The server never pre-collapses; the DOM ships flat and JS folds it, so a
    # no-JS reviewer still sees every block and the markup stays valid.
    assert "<details" not in result
    assert "\\2195" in result  # CSS expander-icon escape survives, not mangled to octal


def test_computed_page_is_linked_not_word_diffed_or_embedded(tmp_path):
    # A page carrying computed output (here a Plotly widget) must not be
    # word-diffed (fragile against volatile rendered markup) nor embedded whole
    # (that would run its scripts in the diff page). When its visible text
    # changes it is shown as a linked summary card with a static-text preview.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = (
        "<html><head></head><body><main>"
        "<p>Revenue was {figure}.</p>"
        '<div class="plotly-graph-div" id="{wid}"></div>'
        '<script type="application/json" data-for="{wid}">{{"x":[{x}]}}</script>'
        "</main></body></html>"
    )
    (old / "index.html").write_text(shell.format(figure="$1M", wid="a1b2", x="1,2,3"))
    (new / "index.html").write_text(shell.format(figure="$2M", wid="z9y8", x="4,5,6"))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    # Linked as an interactive page, not word-diffed: the current visible text
    # shows in the preview, the old value is gone, and none of the page's own
    # <script> is embedded into the diff document.
    assert "interactive page (linked)" in result
    assert "Revenue was $2M." in result
    assert "$1M" not in result
    assert "open the full page" in result
    assert 'type="application/json"' not in result


def test_new_self_contained_page_is_linked_and_carries_no_foreign_script(tmp_path):
    # A brand-new self-contained report (an empty container filled by one large
    # inline data payload — no framework marker) must be linked with a card, not
    # dumped whole: embedding its multi-KB script would bloat the page and, with
    # several such pages, collide.
    new = tmp_path / "new"
    new.mkdir()
    payload = "const DATA_B64='%s';" % ("A" * 40000)
    (new / "report.html").write_text(
        "<html><head></head><body>"
        '<h1>Trajectories</h1><div class="tiles" id="tiles"></div>'
        f"<script>{payload}document.getElementById('tiles').textContent='x';</script>"
        "</body></html>"
    )

    result = WHAT_CHANGED.build(tmp_path / "old", new, "", "PR #1")
    (tmp_path / "old").mkdir(exist_ok=True)

    assert "new page · interactive (linked)" in result
    assert "DATA_B64" not in result  # the payload is not embedded
    assert "Trajectories" in result  # static text still previewed
    assert len(result) < 20000


def test_two_self_contained_pages_do_not_collide(tmp_path):
    # The core failure: two self-contained pages that declare the same top-level
    # identifiers and reuse the same element ids. Embedded whole they would throw
    # "identifier already declared" and leave duplicate ids; linked as cards they
    # carry no script and no widget ids, so nothing collides.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    page = (
        "<html><head></head><body>"
        '<h1>Report {n}</h1><div id="tiles"></div>'
        "<script>const DATA_B64='{blob}';const renderTiles=()=>{{}};</script>"
        "</body></html>"
    )
    (new / "a.html").write_text(page.format(n="A", blob="A" * 40000))
    (new / "b.html").write_text(page.format(n="B", blob="B" * 40000))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert result.count('id="tiles"') == 0
    assert "const DATA_B64" not in result
    assert result.count('class="page-diff new"') == 2
    assert "interactive (linked)" in result


def test_embedded_new_prose_page_is_stripped_of_scripts(tmp_path):
    # An ordinary new prose page is embedded inline (good) but any incidental
    # <script>/<style> it carries is stripped — the diff page runs only its own.
    new = tmp_path / "new"
    new.mkdir()
    (tmp_path / "old").mkdir()
    (new / "page.html").write_text(
        "<html><head></head><body><main>"
        "<p>Fresh prose paragraph.</p>"
        "<script>console.log('should not survive')</script>"
        "<style>.x{color:red}</style>"
        "</main></body></html>"
    )

    result = WHAT_CHANGED.build(tmp_path / "old", new, "", "PR #1")

    assert "Fresh prose paragraph." in result
    assert "should not survive" not in result
    assert ".x{color:red}" not in result


def test_computed_page_data_change_is_reported_even_when_static_text_is_same(tmp_path):
    # Same static text, but changed widget ids / payload: it must be reported.
    # Static text equality cannot prove that client-rendered output is unchanged.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = (
        "<html><head></head><body><main>"
        "<p>Stable prose.</p>"
        '<div class="plotly-graph-div" id="{wid}"></div>'
        '<script type="application/json" data-for="{wid}">{{"id":"{wid}"}}</script>'
        "</main></body></html>"
    )
    (old / "index.html").write_text(shell.format(wid="a1b2c3"))
    (new / "index.html").write_text(shell.format(wid="z9y8x7"))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert "changed · interactive page (linked)" in result
    assert "open the full page" in result


def test_partly_changed_inline_tag_never_wraps_a_lone_tag(tmp_path):
    # A bold wrapper added around text that already existed: the <strong> open
    # and close land in *insert* runs while the word between them stays *equal*.
    # The wrapper must not emit `<ins><strong></ins>` (a lone tag inside <ins>,
    # invalid even if browsers recover) — the half-in tag is emitted bare.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = "<html><head></head><body><main><p>{body}</p></main></body></html>"
    (old / "index.html").write_text(shell.format(body="Guide to research"))
    (new / "index.html").write_text(
        shell.format(body="<strong>Guide</strong> to research")
    )

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert "<ins><strong></ins>" not in result
    assert "<ins></strong></ins>" not in result
    # The bold markup is still applied around the word, just not highlighted.
    assert "<strong>Guide</strong>" in result


def test_fully_inserted_inline_pair_is_still_highlighted(tmp_path):
    # When both halves of an inline pair fall inside the same inserted run, the
    # pair is balanced and stays highlighted inside <ins> (valid nesting).
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = "<html><head></head><body><main><p>Intro. {body}</p></main></body></html>"
    (old / "index.html").write_text(shell.format(body=""))
    (new / "index.html").write_text(shell.format(body="<em>Brand new clause.</em>"))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert "<ins><em>Brand new clause.</em></ins>" in result


def test_own_output_is_never_diffed_as_a_page(tmp_path):
    # A previous run's what-changed.html left in the tree (matched by basename)
    # or any page carrying the generator marker (matched by signature) must not
    # appear as a page in the diff — the generator never diffs its own output.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = "<html><head></head><body><main><p>{t}</p></main></body></html>"
    (old / "index.html").write_text(shell.format(t="Same prose."))
    (new / "index.html").write_text(shell.format(t="Same prose."))
    # A stale artifact from an earlier run, by conventional name...
    (new / "what-changed.html").write_text(
        f"<html><head>{WHAT_CHANGED.WHAT_CHANGED_META}"
        "<title>What changed &middot; PR #4</title></head>"
        '<body><div class="wc-scope"><main>diff</main></div></body></html>'
    )
    # ...and one renamed but still self-identifying by its generator marker.
    (new / "old-diff.html").write_text(
        f"<html><head>{WHAT_CHANGED.WHAT_CHANGED_META}<title>What changed</title>"
        "</head><body><main>stale diff</main></body></html>"
    )

    result = WHAT_CHANGED.build(
        old, new, "", "PR #5", out_path=new / "what-changed.html"
    )

    assert "No rendered content changed" in result
    assert "PR #4" not in result
    assert 'id="p-what-changed"' not in result
    assert "old-diff.html" not in result
    # And the page it emits self-identifies so a later run skips it too.
    assert WHAT_CHANGED.is_what_changed_artifact(result)


def test_same_named_legitimate_page_in_subdirectory_is_not_suppressed(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    (old / "guide").mkdir(parents=True)
    (new / "guide").mkdir(parents=True)
    shell = "<html><head></head><body><main><p>{t}</p></main></body></html>"
    (old / "guide" / "what-changed.html").write_text(shell.format(t="Before"))
    (new / "guide" / "what-changed.html").write_text(shell.format(t="After"))

    result = WHAT_CHANGED.build(
        old, new, "", "PR #5", out_path=new / "what-changed.html"
    )

    assert "guide/what-changed.html" in result
    assert "<del>Before</del>" in result
    assert "<ins>After</ins>" in result


def test_embedded_markup_is_strictly_sanitized(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (new / "index.html").write_text(
        """<html><head></head><body><main>
        <p id="duplicate" onclick="alert(1)">Safe <strong>prose</strong>.</p>
        <a href="java&#x73;cript:alert(1)">bad link</a>
        <img src="https://example.org/chart.png" onerror="alert(1)" alt="chart">
        <iframe srcdoc="<script>alert(1)</script>">hidden</iframe>
        <svg onload="alert(1)"><a href="javascript:alert(1)">svg</a></svg>
        <script src="https://evil.example/x.js">alert(1)</script>
        <style>@import url(https://evil.example/x.css)</style>
        </main></body></html>"""
    )

    result = WHAT_CHANGED.build(old, new, "", "PR #5")
    section = result.split('id="p-index-html"', 1)[1].split("</section>", 1)[0]

    assert "Safe <strong>prose</strong>." in section
    assert 'src="https://example.org/chart.png"' in section
    for forbidden in (
        "onclick",
        "onerror",
        "javascript:",
        "<iframe",
        "<svg",
        "<script",
        "<style",
        'id="duplicate"',
        "evil.example",
    ):
        assert forbidden not in section


def test_large_inline_style_does_not_make_static_page_interactive():
    content = "<style>" + ("x" * 25_000) + "</style><p>Static prose.</p>"

    assert not WHAT_CHANGED.is_script_heavy(content)


def test_markup_only_change_is_annotated_not_embedded(tmp_path):
    # PR #4's only edit to proposal.qmd was inserting an invisible cross-ref
    # anchor `[]{#contributions}` -> an empty <span id="contributions">. The
    # rendered text is unchanged, so the page must be annotated (naming the
    # anchor) and linked, not embedded whole tagged "changed" with nothing lit.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    body = "<h2>Overview</h2><p>Lots of unchanged prose here.</p>"
    shell = "<html><head></head><body><main>{b}</main></body></html>"
    (old / "proposal.html").write_text(
        shell.format(b=body + "<p>Our contributions:</p>")
    )
    (new / "proposal.html").write_text(
        shell.format(
            b=body + '<p><span id="contributions"></span>Our contributions:</p>'
        )
    )

    result = WHAT_CHANGED.build(old, new, "https://x/pr-5", "PR #5")

    assert "non-visible markup only" in result
    assert "anchor added: #contributions" in result
    assert "open the full page" in result
    # It is NOT rendered as a word-level prose diff: the page's own text is not
    # embedded, and the section body carries no highlighted runs.
    assert result.count("Lots of unchanged prose here.") == 0
    section = result.split('id="p-proposal-html"', 1)[1].split("</section>", 1)[0]
    assert "<ins>" not in section and "<del>" not in section


def test_visible_text_change_still_gets_a_full_word_diff(tmp_path):
    # Guard the branch boundary: a real visible edit on a prose page must still
    # produce an inline word diff, not the markup-only annotation.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = "<html><head></head><body><main><p>{t}</p></main></body></html>"
    (old / "index.html").write_text(shell.format(t="Synced 2026-05-17 today."))
    (new / "index.html").write_text(shell.format(t="Synced 2026-08-14 today."))

    result = WHAT_CHANGED.build(old, new, "", "PR #5")

    assert "<del>2026-05-17</del>" in result
    assert "<ins>2026-08-14</ins>" in result
    assert "non-visible markup only" not in result


def test_has_computed_output_detects_widgets_and_ignores_prose():
    assert WHAT_CHANGED.has_computed_output('<div class="cell-output">x</div>')
    assert WHAT_CHANGED.has_computed_output('<div class="observablehq"></div>')
    assert WHAT_CHANGED.has_computed_output(
        '<script type="application/json">{}</script>'
    )
    assert not WHAT_CHANGED.has_computed_output(
        "<p>Just prose with <a href='x'>a link</a> and <code>code</code>.</p>"
    )


def test_page_title_entities_read_as_on_the_page(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "notes.html").write_text(
        "<title>Tea&nbsp;notes: milk &amp; sugar</title><main><p>Old</p></main>"
    )
    (new / "notes.html").write_text(
        "<title>Tea&nbsp;notes: milk &amp; sugar</title><main><p>New</p></main>"
    )

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    assert "&amp;nbsp;" not in result
    assert "&amp;amp;" not in result
    assert '<h2><a href="notes.html">Tea\xa0notes: milk &amp; sugar</a>' in result
    assert '"#p-notes-html">Tea\xa0notes: milk &amp; sugar ' in result


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("&nbsp;Tea&nbsp;", "\xa0Tea\xa0"),
        ("&#160;Tea&#xA0;", "\xa0Tea\xa0"),
        ("&nbsp;", "\xa0"),
        ("\xa0Tea\xa0", "\xa0Tea\xa0"),
        (" \t\nTea&nbsp;notes\r\f ", "Tea\xa0notes"),
        (" \t\r\n\f ", "notes.html"),
    ],
)
def test_page_title_preserves_nonbreaking_spaces(title, expected):
    assert WHAT_CHANGED.page_title(f"<title>{title}</title>", "notes.html") == expected


@pytest.mark.parametrize(
    "title",
    [
        "Tea&#10;notes",
        "Tea&#9;notes",
        "Tea&#13;notes",
        "Tea&#12;notes",
        "Tea &#x9;&#10; \t&#13;notes",
        "&#9;Tea notes&#10;",
    ],
)
def test_page_title_collapses_encoded_html_whitespace(title):
    assert (
        WHAT_CHANGED.page_title(f"<title>{title}</title>", "notes.html") == "Tea notes"
    )


@pytest.mark.parametrize(
    ("old_body", "new_body"),
    [
        ("<p>Old</p>", "<p>New</p>"),
        ('<p id="old">Same</p>', '<p id="new">Same</p>'),
        (None, "<p>New</p>"),
        ("<p>Old</p>", None),
        (
            '<script type="application/json">{"value": 1}</script>',
            '<script type="application/json">{"value": 2}</script>',
        ),
        (None, '<script type="application/json">{"value": 2}</script>'),
        ('<script type="application/json">{"value": 1}</script>', None),
    ],
    ids=[
        "changed",
        "markup-only",
        "new",
        "removed",
        "interactive-changed",
        "interactive-new",
        "interactive-removed",
    ],
)
def test_page_title_markup_stays_escaped_in_every_output_path(
    tmp_path, old_body, new_body
):
    old = tmp_path / "old"
    new = tmp_path / "new"
    encoded_title = "&lt;img src=x onerror=alert(1)&gt; &quot;x&quot;"
    for root, body in ((old, old_body), (new, new_body)):
        root.mkdir()
        if body is not None:
            (root / "notes.html").write_text(
                f"<title>{encoded_title}</title><main>{body}</main>"
            )

    result = WHAT_CHANGED.build(old, new, "", "PR preview")

    # The heading and table of contents display text, never live title markup.
    assert result.count(encoded_title) == 2
    assert "<img" not in result
    assert '"x"' not in result


@pytest.mark.parametrize(
    "href",
    [
        "../../javascript:alert(1)",
        "../../JavaScript:alert(1)",
        "../../data:text/html,x",
        "../../vbscript:x",
        "../../http:evil.example",
    ],
)
def test_rebased_links_never_become_schemes(href):
    result = WHAT_CHANGED.sanitize_fragment(
        f'<p><a href="{href}">x</a><img src="{href}"></p>', "slides/deck/slides.html"
    )

    for attr in re.findall(r'(?:href|src)="([^"]*)"', result):
        assert WHAT_CHANGED.safe_url(attr)
        assert ":" not in attr.split("/", 1)[0]


def test_rebased_link_keeps_ordinary_relative_targets():
    result = WHAT_CHANGED.sanitize_fragment(
        '<a href="../../lit-review/">x</a>', "slides/deck/slides.html"
    )

    assert 'href="lit-review/"' in result


@pytest.mark.parametrize("source", ["notes.html", "reports/notes.html"])
def test_query_only_links_keep_their_source_page(source):
    result = WHAT_CHANGED.sanitize_fragment(
        '<a href="?view=full#details">details</a><a href="#local">local</a>', source
    )
    assert f'href="{source}?view=full#details"' in result
    assert 'href="#local"' in result


@pytest.mark.parametrize("edit", ["insert", "delete", "replace", "separated"])
def test_large_repetitive_page_comparison_finishes_promptly(tmp_path, edit):
    """A local edit must not spend minutes matching repeated prose or markup."""
    before = "<p>" + "research finding " * 15_000 + "</p>"
    if edit == "insert":
        after = before.replace("finding", "newfinding", 1)
    elif edit == "delete":
        after = before.replace("research finding ", "", 1)
    elif edit == "replace":
        after = before.replace("research", "revisedresearch")
    else:
        after = before.replace("<p>", "<p>firstedit ").replace("</p>", " lastedit</p>")
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "index.html").write_text(f"<main>{before}</main>")
    (new / "index.html").write_text(f"<main>{after}</main>")
    report = tmp_path / "comparison.html"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--old",
            str(old),
            "--new",
            str(new),
            "--out",
            str(report),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    markup = report.read_text()
    assert "<ins" in markup or "<del" in markup
    if edit == "separated":
        assert "firstedit" in markup and "lastedit" in markup
    elif edit in {"replace", "insert"}:
        assert "revisedresearch" in markup or "newfinding" in markup


def test_retained_render_theme_prefix_preserves_external_urls_and_fragments(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (new / "index.html").write_text(
        '<head><link rel="stylesheet" href="site_libs/bootstrap.css?version=2&amp;x=1">'
        '<link rel="stylesheet" href="https://example.org/remote.css">'
        '<link rel="stylesheet" href="//example.org/remote.css">'
        '<style>body { background: url("images/background.png"); }'
        ".icon { mask: url(#icon); }</style></head><main>New text</main>"
    )
    result = WHAT_CHANGED.build(
        old,
        new,
        "",
        "Local comparison",
        theme_url_prefix="what-changed-assets/",
    )
    assert (
        'href="what-changed-assets/site_libs/bootstrap.css?version=2&amp;x=1"' in result
    )
    assert 'href="https://example.org/remote.css"' in result
    assert 'href="//example.org/remote.css"' in result
    assert 'url("what-changed-assets/images/background.png")' in result
    assert "url(#icon)" in result


def test_retained_render_is_excluded_from_page_and_theme_discovery(tmp_path):
    (tmp_path / "index.html").write_text("<main>The actual preview</main>")
    assets = tmp_path / "what-changed-assets"
    assets.mkdir()
    (assets / "index.html").write_text("<main>Prior comparison render</main>")
    assert list(WHAT_CHANGED.list_pages(tmp_path, reserved_local_output=True)) == [
        "index.html"
    ]


def test_nonlocal_comparison_preserves_pages_with_local_reserved_names(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (new / "what-changed-assets").mkdir(parents=True)
    (new / "what-changed.html").write_text("<main>A legitimate site page.</main>")
    (new / "what-changed-assets/details.html").write_text(
        "<main>Legitimate project details.</main>"
    )

    result = WHAT_CHANGED.build(old, new, "", "PR comparison")

    assert "A legitimate site page" in result
    assert "Legitimate project details" in result


@pytest.mark.parametrize("url", ["image.png?x=1&y=2", "image.png?x=1&amp;y=2"])
def test_retained_inline_css_preserves_raw_url_ampersands(tmp_path, url):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (new / "index.html").write_text(
        f'<head><style>body {{ background: url("{url}"); }}</style></head>'
        "<main>A new finding.</main>"
    )

    result = WHAT_CHANGED.build(
        old, new, "", "Local comparison", theme_url_prefix="what-changed-assets/"
    )

    assert f'url("what-changed-assets/{url}")' in result


@pytest.mark.parametrize("nested", [False, True])
def test_retained_theme_rebases_quoted_css_urls_and_imports(tmp_path, nested):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    page = new / "chapters/index.html" if nested else new / "index.html"
    page.parent.mkdir(parents=True)
    source_prefix = "../" if nested else ""
    page.write_text(
        "<head><style>\n"
        f'@import "{source_prefix}themes/my theme.css" screen;\n'
        f"@import '{source_prefix}themes/print.css' print;\n"
        f'@import url("{source_prefix}themes/another theme.css");\n'
        f"body {{ background: URL( '{source_prefix}images/picture (dark).png' ); }}\n"
        f".icon {{ mask: url({source_prefix}images/icon.svg); }}\n"
        f'.quoted {{ background: url("{source_prefix}images/a\\"b.png"); }}\n'
        '@import "https://example.org/remote theme.css";\n'
        '@import "//example.org/remote.css";\n'
        '.remote { background: url("https://example.org/bg image.png"); }\n'
        '.inline { background: url("data:image/svg+xml;utf8,(svg)"); }\n'
        '.fragment { mask: url("#icon"); }\n'
        '/* @import "ignored.css"; url("ignored image.png") */\n'
        ".content { content: 'url(\"literal text.png\")'; }\n"
        "</style></head><main>A new finding.</main>"
    )

    result = WHAT_CHANGED.build(
        old, new, "", "Local comparison", theme_url_prefix="what-changed-assets/"
    )

    assert '@import "what-changed-assets/themes/my theme.css" screen;' in result
    assert "@import 'what-changed-assets/themes/print.css' print;" in result
    assert '@import url("what-changed-assets/themes/another theme.css");' in result
    assert "URL( 'what-changed-assets/images/picture (dark).png' )" in result
    assert "url(what-changed-assets/images/icon.svg)" in result
    assert 'url("what-changed-assets/images/a\\"b.png")' in result
    assert '@import "https://example.org/remote theme.css";' in result
    assert '@import "//example.org/remote.css";' in result
    assert 'url("https://example.org/bg image.png")' in result
    assert 'url("data:image/svg+xml;utf8,(svg)")' in result
    assert 'url("#icon")' in result
    assert '/* @import "ignored.css"; url("ignored image.png") */' in result
    assert "content: 'url(\"literal text.png\")'" in result


def _ev_popover_parents(doc):
    """(tag, class) of the direct parent of every `.ev-pop` in `doc`."""
    from html.parser import HTMLParser

    void = {"br", "img", "meta", "link", "hr", "input", "wbr", "source", "col"}

    class P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack = []
            self.parents = []

        def handle_starttag(self, tag, attrs):
            cls = dict(attrs).get("class", "")
            if "ev-pop" in cls.split():
                self.parents.append(self.stack[-1] if self.stack else (None, None))
            if tag not in void:
                self.stack.append((tag, cls))

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    break

    p = P()
    p.feed(doc)
    return p.parents


def _ev_page(claim, popover=""):
    pop = (
        f'<span class="ev-pop" role="note"><span class="ev-card">'
        f'<span class="ev-pop-text ev-quote">“<em>{popover}</em>”</span>'
        f"</span></span>"
        if popover
        else ""
    )
    return (
        "<html><head></head><body><main><p>Kosmos averages "
        f'<span class="ev" role="note">{claim}{pop}</span> per run.</p>'
        "</main></body></html>"
    )


def test_added_evidence_is_chipped_and_its_popover_stays_a_direct_child(tmp_path):
    """An added quote must be visible and must still hover.

    Both halves failed on a real PR: the inserted popover was word-diffed into
    the `<ins>` wrapper, which breaks `.ev:hover > .ev-pop` so nothing appeared,
    and the only marker of the addition lived inside that hidden popover.
    """
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "index.html").write_text(_ev_page("42,000 lines of code"))
    (new / "index.html").write_text(
        _ev_page("42,000 lines of code", "executing an average of 42,000 lines")
    )

    result = WHAT_CHANGED.build(old, new, "", "PR #9")

    assert "wc-ev-add" in result
    assert "evidence added" in result
    assert ".wc-scope .wc-ev-chip.wc-ev-add { background: var(--wc-new); }" in result
    # The popover is restored outside the <ins> wrapper, as a child of `.ev`.
    assert _ev_popover_parents(result) == [("span", "ev")]
    # Its quote is not word-diffed into hidden <ins>/<del> runs.
    quote = re.search(r'<span class="ev-pop".*?</em>', result, re.S).group(0)
    assert "<ins>" not in quote and "<del>" not in quote


def test_single_quoted_evidence_popover_is_extracted():
    content = (
        "<span class='ev-pop extra' role='note'>"
        "<span class='ev-card'>quote</span></span>"
    )

    extracted, store = WHAT_CHANGED.extract_ev_popovers(content)

    assert extracted.startswith('<wc-evpop data-k="')
    assert list(store.values()) == [content]


def test_similar_class_name_is_not_extracted_as_evidence_popover():
    content = '<span class="ev-pop-text">quote</span>'

    extracted, store = WHAT_CHANGED.extract_ev_popovers(content)

    assert extracted == content
    assert store == {}


def test_data_class_is_not_extracted_as_evidence_popover():
    content = '<span data-class="ev-pop">quote</span>'

    extracted, store = WHAT_CHANGED.extract_ev_popovers(content)

    assert extracted == content
    assert store == {}


def test_custom_span_element_does_not_affect_popover_depth():
    content = (
        '<span class="ev-pop"><span-foo />quote</span>'
        '<span-foo class="ev-pop">not evidence</span-foo>'
    )

    extracted, store = WHAT_CHANGED.extract_ev_popovers(content)

    assert extracted.startswith('<wc-evpop data-k="')
    assert extracted.endswith('<span-foo class="ev-pop">not evidence</span-foo>')
    assert list(store.values()) == [content.split("<span-foo class", 1)[0]]


def test_unchanged_evidence_is_not_rediffed_when_prose_changes(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "index.html").write_text(_ev_page("42,000 lines", "an average of 42,000"))
    (new / "index.html").write_text(_ev_page("42,000 lines", "an average of 42,000"))
    (new / "about.html").write_text(
        "<html><head></head><body><main><p>New page.</p></main></body></html>"
    )
    (old / "about.html").write_text(
        "<html><head></head><body><main><p>Old page.</p></main></body></html>"
    )

    result = WHAT_CHANGED.build(old, new, "", "PR #10")

    assert "wc-ev-chip" not in result.split("DIFF_STYLE")[-1].split("<body")[-1]
    assert "evidence added" not in result
    assert "evidence removed" not in result


def test_removed_evidence_is_reported_on_the_claim(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "index.html").write_text(_ev_page("42,000 lines", "an average of 42,000"))
    (new / "index.html").write_text(_ev_page("42,000 lines"))

    result = WHAT_CHANGED.build(old, new, "", "PR #11")

    assert "evidence removed" in result
    # The stale quote is not carried into the new state.
    assert "an average of 42,000" not in result
    assert _ev_popover_parents(result) == []


def test_citation_links_point_at_the_full_page_bibliography(tmp_path):
    # Quarto renders citations as `#ref-<key>` links to the page's own
    # bibliography, which the excerpt lacks; they must deep-link the full page.
    old = tmp_path / "old"
    new = tmp_path / "new"
    (old / "sub").mkdir(parents=True)
    (new / "sub").mkdir(parents=True)
    shell = (
        "<html><head></head><body><main><p>{text} "
        '<a href="#ref-he2026" role="doc-biblioref">He et al. 2026</a></p>'
        "</main></body></html>"
    )
    (old / "sub" / "page.html").write_text(shell.format(text="Old claim."))
    (new / "sub" / "page.html").write_text(shell.format(text="New claim."))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")
    assert 'href="sub/page.html#ref-he2026"' in result
    assert 'href="#ref-he2026"' not in result

    result = WHAT_CHANGED.build(old, new, "https://example.org/pr-1/", "PR #1")
    assert 'href="https://example.org/pr-1/sub/page.html#ref-he2026"' in result
