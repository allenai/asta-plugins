"""Tests for the rendered Quarto preview diff generator."""

import html
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
ENGINE_SCRIPT = SCRIPT.with_name("diff-engine.py")
ENGINE_SPEC = importlib.util.spec_from_file_location("diff_engine", ENGINE_SCRIPT)
ENGINE = importlib.util.module_from_spec(ENGINE_SPEC)
ENGINE_SPEC.loader.exec_module(ENGINE)


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
        "Changes marked</button>"
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
    assert '<li><a href="#paper-diff">Paper</a> <span class="tag removed">' in result
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
    assert ".wc-strip" in result
    assert "unchanged " in result
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
    assert 'class="wc-strip"' not in result  # the strips are made in the browser


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
    # the page and its scripts, smaller than the 40000-byte payload it did not embed
    assert len(result) < 40000


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
    # The bold markup is still applied around the word; the new tag is marked
    # (the word did not change), not wrapped in <ins>.
    assert re.search(r'<strong class="wc-fmt-changed"[^>]*>Guide</strong>', result)


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
        "onload",
        "<script",
        "<style",
        'id="duplicate"',
        "evil.example",
    ):
        assert forbidden not in section
    # a drawing is kept as a safe subset: its element and its text, no handler
    # and no script link
    assert "<svg><a>svg</a></svg>" in section


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


QUARTO_DOT = (
    '<div class="cell" data-layout-align="default"><div class="cell-output-display">'
    '<div><figure class="figure"><div><svg width="62" height="116">'
    '<g class="graph"><title>G</title><text x="1">a</text></g></svg></div></figure>'
    "</div></div></div>"
)
QUARTO_MERMAID = (
    '<div class="cell" data-layout-align="default"><div class="cell-output-display">'
    '<div><figure class="figure"><div><pre class="mermaid mermaid-js">'
    "flowchart LR\n  A --&gt; B\n</pre></div></figure></div></div></div>"
)


def test_a_cell_whose_output_is_a_drawing_is_not_computed_output():
    # Quarto's Graphviz cell arrives as an inline svg and its Mermaid cell as the
    # diagram's text: static kinds of the engine, so the page is compared.
    for cell in (QUARTO_DOT, QUARTO_MERMAID):
        assert not WHAT_CHANGED.has_computed_output(f"<p>Prose.</p>{cell}")
    # a cell with a computed part beside the drawing, and any other cell output
    # (a table, a picture, a widget), still is
    plot = '<div class="cell-output-display"><img src="p.png"></div>'
    for other in (plot, '<div class="cell-output">x</div>'):
        assert WHAT_CHANGED.has_computed_output(QUARTO_DOT + other)
    assert WHAT_CHANGED.has_computed_output(
        QUARTO_DOT.replace("</svg>", "</svg><img src='x.png'>")
    )


def test_a_page_with_a_changed_diagram_cell_shows_old_and_new_not_a_card(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for root, label in ((old, "a"), (new, "b")):
        root.mkdir()
        (root / "p.html").write_text(
            "<main><p>Same words.</p>"
            + QUARTO_DOT.replace(">a<", f">{label}<")
            + QUARTO_MERMAID.replace("A --&gt; B", f"A --&gt; {label.upper()}")
            + "</main>"
        )
    result = WHAT_CHANGED.build(old, new, "", "PR")
    assert "renders its content with client-side scripts" not in result
    # each cell is one edited block, its old and new drawing side by side in it
    assert re.search(r'</svg></del>\s*<ins class="wc-unit"><svg', result)
    assert re.search(r'</pre></del>\s*<ins class="wc-unit"><pre class="mermaid', result)
    assert result.count('<del class="wc-unit"><svg') == 1
    assert result.count('<ins class="wc-unit"><pre class="mermaid') == 1
    assert "A --&gt; A" in result and "A --&gt; B" in result


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
    assert '<li><a href="#p-notes-html">Tea\xa0notes: milk &amp; sugar</a>' in result


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


def test_quartos_support_files_are_not_pages_of_the_site(tmp_path):
    """reveal.js's speaker view appears with the first deck; it is not a new page."""
    (tmp_path / "index.html").write_text("<main>The site</main>")
    speaker = tmp_path / "site_libs/revealjs/plugin/notes"
    speaker.mkdir(parents=True)
    (speaker / "speaker-view.html").write_text("<html>speaker notes</html>")
    assert list(WHAT_CHANGED.list_pages(tmp_path)) == ["index.html"]


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


def test_a_whole_added_claim_keeps_its_popover_and_focus(tmp_path):
    """A claim added in a replaced run must still open its quote on hover/focus.

    The claim's own `<span class="ev">` used to be wrapped in `<ins>` while its
    popover was restored outside it, so the browser closed the claim at
    `</ins>` and the popover became a sibling; `tabindex` was also sanitized.
    """
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    pop = (
        '<span class="ev-pop" role="note"><span class="ev-card">'
        '<span class="ev-pop-text ev-quote">“<em>We introduce BERT.</em>”</span>'
        "</span></span>"
    )
    page = "<html><head></head><body><main><p>Intro. {} end.</p></main></body></html>"
    (old / "index.html").write_text(page.format("The"))
    (new / "index.html").write_text(
        page.format(
            '<span class="ev" tabindex="0" role="note" aria-description="q">'
            f"BERT later applied it{pop}</span>"
        )
    )

    result = WHAT_CHANGED.build(old, new, "", "PR #12")

    assert "evidence added" in result
    assert _ev_popover_parents(result) == [("span", "ev")]
    claim = re.search(r'<span class="ev"[^>]*>', result).group(0)
    assert 'tabindex="0"' in claim
    assert "<ins>BERT later applied it</ins>" in result


def test_sanitizer_keeps_only_unobtrusive_tabindex():
    out = WHAT_CHANGED.sanitize_fragment(
        '<span class="ev" tabindex="0">a</span><span tabindex="5">b</span>'
    )
    assert '<span class="ev" tabindex="0">' in out
    assert 'tabindex="5"' not in out


def test_single_quoted_evidence_popover_is_extracted():
    content = (
        "<span class='ev-pop extra' role='note'>"
        "<span class='ev-card'>quote</span></span>"
    )

    extracted, store = ENGINE.extract_ev_popovers(content)

    assert extracted.startswith('<wc-evpop data-k="')
    assert list(store.values()) == [content]


def test_similar_class_name_is_not_extracted_as_evidence_popover():
    content = '<span class="ev-pop-text">quote</span>'

    extracted, store = ENGINE.extract_ev_popovers(content)

    assert extracted == content
    assert store == {}


def test_data_class_is_not_extracted_as_evidence_popover():
    content = '<span data-class="ev-pop">quote</span>'

    extracted, store = ENGINE.extract_ev_popovers(content)

    assert extracted == content
    assert store == {}


def test_custom_span_element_does_not_affect_popover_depth():
    content = (
        '<span class="ev-pop"><span-foo />quote</span>'
        '<span-foo class="ev-pop">not evidence</span-foo>'
    )

    extracted, store = ENGINE.extract_ev_popovers(content)

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

    assert 'class="wc-ev-chip' not in result  # (the fold script names the class)
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


def _rows(*rows):
    return (
        "<table><tbody>"
        + "".join(
            "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
            for row in rows
        )
        + "</tbody></table>"
    )


def _row_tags(body):
    return re.findall(r"<tr\b[^>]*>.*?</tr>", body)


def test_edited_block_is_one_copy_with_the_removed_word_before_the_added_one():
    # One word edited in a paragraph, a list item and a table cell: each block
    # (p / li / tr) is drawn once, in its own tag with no shade, the removed word
    # in <del> right before the added word in <ins>; the unchanged sibling
    # blocks have neither.
    def page(para, item, cell):
        return (
            f"<p>{para}</p><p>Untouched paragraph.</p>"
            f"<ul><li>{item}</li><li>Untouched item</li></ul>"
            + _rows((cell, "x"), ("Untouched cell", "y"))
        )

    body, changed = WHAT_CHANGED.diff_content(
        page("The model is fast.", "Pick a red apple", "alpha beta"),
        page("The model is slow.", "Pick a green apple", "alpha gamma"),
    )
    assert changed
    assert "<p>The model is <del>fast.</del><ins>slow.</ins></p>" in body
    assert "<li>Pick a <del>red</del><ins>green</ins> apple</li>" in body
    assert "<tr><td>alpha <del>beta</del><ins>gamma</ins></td><td>x</td></tr>" in body
    assert "<p>Untouched paragraph.</p>" in body
    assert "<li>Untouched item</li>" in body
    assert "<tr><td>Untouched cell</td><td>y</td></tr>" in body
    assert "wc-edit" not in body and "wc-block" not in body  # no shade on an edit


def test_phrase_replaced_word_for_word_is_one_mark_on_each_side():
    # The spaces between replaced words match as unchanged, but a reader sees one
    # changed phrase, as on GitHub: one <del> run, one <ins> run, spaces inside.
    body, _ = WHAT_CHANGED.diff_content(
        "<p>Pick one two three here</p>", "<p>Pick a b c here</p>"
    )
    assert "<p>Pick <del>one two three</del><ins>a b c</ins> here</p>" in body
    # An unchanged word between two marks still keeps them apart.
    body, _ = WHAT_CHANGED.diff_content(
        "<p>one two three four five</p>", "<p>a two b four c</p>"
    )
    assert body.count("<ins>") == 3 and body.count("<del>") == 3


def test_row_inserted_between_similar_rows_is_one_added_row():
    old = _rows(("alice", "10"), ("carol", "12"))
    new = _rows(("alice", "10"), ("alicia", "11"), ("carol", "12"))
    body, changed = WHAT_CHANGED.diff_content(old, new)
    assert changed
    rows = _row_tags(body)
    assert len(rows) == 3
    assert rows[0] == "<tr><td>alice</td><td>10</td></tr>"
    assert rows[1] == (
        '<tr class="wc-block-added"><td><ins>alicia</ins></td>'
        "<td><ins>11</ins></td></tr>"
    )
    assert rows[2] == "<tr><td>carol</td><td>12</td></tr>"


def test_two_rows_swapped_never_put_a_removed_rows_words_in_its_neighbour():
    old = _rows(("alice", "10"), ("bob", "11"))
    new = _rows(("bob", "11"), ("alice", "10"))
    body, changed = WHAT_CHANGED.diff_content(old, new)
    assert changed
    rows = _row_tags(body)
    assert len(rows) == 3  # a moved row reads as removed once, added once
    for row in rows:
        if "wc-block-added" in row:
            assert "<del>" not in row and "<ins>" in row
        elif "wc-block-removed" in row:
            assert "<ins>" not in row and "<del>" in row
        else:
            assert "<ins>" not in row and "<del>" not in row
    assert sum("wc-block-added" in row for row in rows) == 1
    assert sum("wc-block-removed" in row for row in rows) == 1


def test_link_whose_boundary_moves_keeps_its_old_target_in_the_one_block():
    # "alpha beta" was the old-paper link and is plain text now; "gamma" is the
    # new-paper link. The removed citation must stay visible, marked, in the
    # one rendered paragraph, and the new link stays a balanced <a>.
    body, changed = WHAT_CHANGED.diff_content(
        '<p>see <a href="old-paper">alpha beta</a> gamma old</p>',
        '<p>see alpha beta <a href="new-paper">gamma</a> new</p>',
    )
    assert changed
    assert body.count("<p>") == 1
    assert 'href="new-paper"' in body
    assert 'data-wc-was="old-paper"' in body
    assert 'class="wc-link-was' in body
    assert body.count("<a ") == body.count("</a>") == 1  # the old one is no <a>


def test_link_removed_from_unchanged_words_keeps_its_old_target():
    body, changed = WHAT_CHANGED.diff_content(
        '<p>see <a href="old-paper">alpha beta</a> now</p>',
        "<p>see alpha beta now</p>",
    )
    assert changed
    assert 'data-wc-was="old-paper"' in body
    assert "<a " not in body


def test_removed_empty_cell_keeps_the_values_under_their_headers():
    # Column B (a blank data cell) is deleted while another cell is edited: the
    # combined grid keeps B's header and B's empty cell, so x stays under C.
    def table(headers, *rows):
        return (
            "<table><tr>"
            + "".join(f"<th>{h}</th>" for h in headers)
            + "</tr>"
            + "".join(
                "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
            )
            + "</table>"
        )

    body, changed = WHAT_CHANGED.diff_content(
        table("ABC", ("shared old", "", "x")),
        table("AC", ("shared new", "x")),
    )
    assert changed
    header, data = _row_tags(body)
    heads = re.findall(r"<th\b[^>]*>(.*?)</th>", header)
    cells = re.findall(r"<td\b[^>]*>(.*?)</td>", data)
    assert len(heads) == len(cells) == 3
    assert heads[2] == "C" and cells[2] == "x"
    assert "wc-block-removed" in header and cells[1] == ""
    assert re.findall(r"<td\b([^>]*)>", data)[1].strip() == 'class="wc-block-removed"'


def test_removed_empty_cell_keeps_its_colspan():
    body, _ = WHAT_CHANGED.diff_content(
        '<table><tr><td>shared old</td><td colspan="2"></td><td>x</td></tr></table>',
        "<table><tr><td>shared new</td><td>x</td></tr></table>",
    )
    assert '<td colspan="2" class="wc-block-removed"></td>' in body or (
        '<td class="wc-block-removed" colspan="2"></td>' in body
    )


def _luminance(color):
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    )
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _dark_vars(css, selector):
    """The custom properties set by the rule with this exact selector."""
    block = re.search(re.escape(selector) + r"\s*\{([^{}]*)\}", css).group(1)
    return dict(re.findall(r"(--wc-[\w-]+):\s*(#[0-9a-fA-F]{6})", block))


def test_dark_source_words_stand_off_their_line_tint_and_keep_text_legible():
    css = WHAT_CHANGED.DIFF_STYLE
    page = _dark_vars(css, '[data-wc-mode="dark"] .wc-scope')
    src = _dark_vars(css, '[data-wc-mode="dark"] .wc-scope .wc-src')
    standalone = _dark_vars(
        css, "@media (prefers-color-scheme: dark) { .wc-scope.wc-standalone .wc-src"
    )
    assert src == standalone  # the same shades with a theme and without
    for side in ("ins", "del"):
        word, line = src[f"--wc-{side}-bg"], page[f"--wc-{side}-blk"]
        assert _contrast(word, line) >= 1.5
        # Light text (GitHub's and Bootstrap's dark body colours) on the words.
        for text in ("#e6edf3", "#dee2e6"):
            assert _contrast(text, word) >= 4.5
    # Rendered pages have no line tint: their dark word marks stay as they were,
    # so a link inside a mark keeps its contrast.
    assert (page["--wc-ins-bg"], page["--wc-del-bg"]) == ("#1b4d0f", "#6b1f22")


def test_removed_link_marker_text_is_readable_in_light_and_dark():
    css = WHAT_CHANGED.DIFF_STYLE
    rule = re.search(r"\.wc-link-gone::before\s*\{([^{}]*)\}", css).group(1)
    color = (
        re.search(r"(?<![-\w])color:\s*([^;]+);", rule).group(1).strip()
        if (re.search(r"(?<![-\w])color:", rule))
        else "inherit"
    )
    light_bg = "#f7b9b1"
    dark_bg = _dark_vars(css, '[data-wc-mode="dark"] .wc-scope')["--wc-del-bg"]
    assert re.search(r"--wc-del-bg:\s*" + light_bg, css)
    # What the marker's text colour is: muted text, or the surrounding text,
    # which is dark on a light page and light on a dark one (GitHub's and
    # Bootstrap's body colours).
    if color == "var(--wc-muted)":
        light_text, dark_text = ["#57606a"], ["#8b949e"]
    else:
        assert color == "inherit"
        light_text, dark_text = ["#1f2328", "#212529"], ["#e6edf3", "#dee2e6"]
    for text in light_text:
        assert _contrast(text, light_bg) >= 4.5
    for text in dark_text:
        assert _contrast(text, dark_bg) >= 4.5


def test_paragraph_split_in_two_keeps_two_paragraphs():
    body, changed = WHAT_CHANGED.diff_content(
        "<p>Alpha beta gamma. Delta epsilon zeta.</p>",
        "<p>Alpha beta gamma.</p><p>Delta epsilon zeta.</p>",
    )
    assert changed
    assert body == (
        "<p>Alpha beta gamma. <del>Delta epsilon zeta.</del></p>"
        '<p class="wc-block-added"><ins>Delta epsilon zeta.</ins></p>'
    )


def test_column_added_marks_only_the_new_cells():
    old = _rows(("a", "b"), ("c", "d"))
    new = _rows(("a", "x", "b"), ("c", "y", "d"))
    body, changed = WHAT_CHANGED.diff_content(old, new)
    assert changed
    assert body.count('<td class="wc-block-added">') == 2
    assert "<ins>x</ins>" in body and "<ins>y</ins>" in body
    assert body.count("<ins>") == 2
    assert "<del>" not in body
    assert "wc-edit" not in body


def test_edited_cell_beside_an_added_column_is_one_row_with_the_new_cell_shaded():
    old = _rows(("a", "b c"))
    new = _rows(("a", "x", "b d"))
    body, _ = WHAT_CHANGED.diff_content(old, new)
    (row,) = _row_tags(body)
    assert row == (
        '<tr><td>a</td><td class="wc-block-added"><ins>x</ins></td>'
        "<td>b <del>c</del><ins>d</ins></td></tr>"
    )


def _headed(headers, *rows):
    return (
        "<table><thead><tr>"
        + "".join(f"<th>{h}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
        )
        + "</tbody></table>"
    )


def test_edited_number_beside_an_added_column_stays_under_its_header():
    # B's value 2 -> 3 shares no word with the new column's 4: each row still
    # has one cell per header, the edit in B's column, the new cell under C.
    body, changed = WHAT_CHANGED.diff_content(
        _headed("AB", ("1", "2"), ("5", "6")),
        _headed("ABC", ("1", "3", "4"), ("5", "6", "7")),
    )
    assert changed
    header, first, second = _row_tags(body)
    assert len(re.findall(r"<t[hd]\b", header)) == 3
    assert len(re.findall(r"<td\b", first)) == len(re.findall(r"<td\b", second)) == 3
    cells = re.findall(r"<td\b[^>]*>.*?</td>", first)
    assert cells[1] == "<td><del>2</del><ins>3</ins></td>"
    assert cells[2] == '<td class="wc-block-added"><ins>4</ins></td>'


def test_edited_number_beside_a_removed_column_stays_under_its_header():
    body, _ = WHAT_CHANGED.diff_content(
        _headed("ABC", ("1", "3", "4")),
        _headed("AB", ("1", "2")),
    )
    header, row = _row_tags(body)
    assert len(re.findall(r"<th\b", header)) == len(re.findall(r"<td\b", row)) == 3
    cells = re.findall(r"<td\b[^>]*>.*?</td>", row)
    assert cells[1] == "<td><del>3</del><ins>2</ins></td>"
    assert cells[2] == '<td class="wc-block-removed"><del>4</del></td>'


def _cells(row):
    return re.findall(r"<t[dh]\b[^>]*>.*?</t[dh]>", row)


def test_unchanged_row_is_drawn_under_the_new_headers_when_a_column_moved():
    # Headers A,B -> B,C with the byte-identical row [1,2]: the row is not the
    # same row any more (1 left with A, 2 is under B, C holds a new 2).
    body, changed = WHAT_CHANGED.diff_content(
        _headed("AB", ("1", "2")), _headed("BC", ("1", "2"))
    )
    assert changed
    header, row = _row_tags(body)
    assert len(_cells(header)) == len(_cells(row)) == 3
    first, middle, last = _cells(row)
    assert "<del>1</del>" in first and "wc-block-removed" in first
    assert "<ins>2</ins>" in last and "wc-block-added" in last
    assert "<del>2</del>" in middle and "<ins>1</ins>" in middle


def test_unchanged_tbody_is_drawn_under_the_new_headers_when_a_column_moved():
    old = (
        "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
        "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
    )
    new = (
        "<table><thead><tr><th>B</th><th>C</th></tr></thead>"
        "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
    )
    body, _ = WHAT_CHANGED.diff_content(old, new)
    row = _row_tags(body)[1]
    assert len(_cells(row)) == 3
    assert "<del>1</del>" in _cells(row)[0]
    assert "<ins>2</ins>" in _cells(row)[2]


def test_removed_row_keeps_its_values_under_their_headers_beside_an_added_column():
    # Old A,B rows [stay,1],[gone,2]; new A,C,B row [stay,x,1]: the removed row's
    # 2 is under B, with an empty cell under the added C.
    body, _ = WHAT_CHANGED.diff_content(
        _headed("AB", ("stay", "1"), ("gone", "2")),
        _headed("ACB", ("stay", "x", "1")),
    )
    header, kept, gone = _row_tags(body)
    assert len(_cells(header)) == len(_cells(kept)) == len(_cells(gone)) == 3
    first, middle, last = _cells(gone)
    assert "<del>gone</del>" in first
    assert "<del>" not in middle and "gone" not in middle
    assert "<del>2</del>" in last
    assert 'class="wc-block-removed"' in gone.split(">")[0] + ">"


def test_added_row_keeps_its_values_under_their_headers_beside_a_removed_column():
    body, _ = WHAT_CHANGED.diff_content(
        _headed("ACB", ("stay", "x", "1")),
        _headed("AB", ("stay", "1"), ("new", "2")),
    )
    header, kept, added = _row_tags(body)
    assert len(_cells(header)) == len(_cells(kept)) == len(_cells(added)) == 3
    first, middle, last = _cells(added)
    assert "<ins>new</ins>" in first
    assert "<ins>" not in middle
    assert "<ins>2</ins>" in last


def test_removed_tbody_keeps_its_values_under_their_headers_beside_an_added_column():
    old = (
        "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
        "<tbody><tr><td>stay</td><td>1</td></tr></tbody>"
        "<tbody><tr><td>gone</td><td>2</td></tr></tbody></table>"
    )
    new = (
        "<table><thead><tr><th>A</th><th>C</th><th>B</th></tr></thead>"
        "<tbody><tr><td>stay</td><td>x</td><td>1</td></tr></tbody></table>"
    )
    body, _ = WHAT_CHANGED.diff_content(old, new)
    gone = _row_tags(body)[-1]
    assert len(_cells(gone)) == 3
    assert "<del>2</del>" in _cells(gone)[2]
    assert "<del>" not in _cells(gone)[1]


def test_table_only_realigned_is_not_a_change():
    body, changed = WHAT_CHANGED.diff_content(
        '<table><tr><td style="text-align:left">a</td><td>b</td></tr></table>',
        '<table><tr><td align="right">a</td><td>b</td></tr></table>',
    )
    assert not changed
    assert "<ins>" not in body and "<del>" not in body and "wc-block" not in body


def test_link_whose_target_changed_marks_its_text_and_shows_old_and_new():
    body, changed = WHAT_CHANGED.diff_content(
        '<p>See <a href="/a">the docs</a> now.</p>',
        '<p>See <a href="/b">the docs</a> now.</p>',
    )
    assert changed
    assert 'class="wc-link-changed"' in body
    assert 'href="/b"' in body and 'data-wc-was="/a"' in body
    assert "<ins>" not in body and "<del>" not in body  # the text did not change
    assert body.count("<a ") == 1  # one link: the new target, the old beside it


def test_page_with_only_a_changed_link_target_is_shown(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    for root, target in ((old, "/a"), (new, "/b")):
        root.mkdir()
        (root / "index.html").write_text(
            f'<main><p>See <a href="{target}">the docs</a>.</p></main>'
        )

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert 'class="wc-link-changed"' in result
    assert 'data-wc-was="/a"' in result


def test_list_item_removed_from_a_nested_list_is_one_removed_item():
    body, changed = WHAT_CHANGED.diff_content(
        "<ul><li>One<ul><li>a</li><li>b</li></ul></li><li>Two</li></ul>",
        "<ul><li>One<ul><li>a</li></ul></li><li>Two</li></ul>",
    )
    assert changed
    assert body == (
        "<ul><li>One<ul><li>a</li>"
        '<li class="wc-block-removed"><del>b</del></li></ul></li><li>Two</li></ul>'
    )


def test_edited_item_draws_its_nested_list_in_the_same_item():
    body, changed = WHAT_CHANGED.diff_content(
        "<ul><li>One two<ul><li>a</li><li>b</li></ul></li></ul>",
        "<ul><li>One three<ul><li>a</li></ul></li></ul>",
    )
    assert changed
    assert body == (
        "<ul><li>One <del>two</del><ins>three</ins><ul><li>a</li>"
        '<li class="wc-block-removed"><del>b</del></li></ul></li></ul>'
    )


def test_edit_in_a_nested_item_leaves_the_outer_item_unmarked():
    body, _ = WHAT_CHANGED.diff_content(
        "<ul><li>One<ul><li>red apple</li></ul></li></ul>",
        "<ul><li>One<ul><li>green apple</li></ul></li></ul>",
    )
    assert body == (
        "<ul><li>One<ul><li><del>red</del><ins>green</ins> apple</li></ul></li></ul>"
    )


def test_removed_block_keeps_its_tags_and_drops_its_ids():
    body, changed = WHAT_CHANGED.diff_content(
        '<h2 id="x">Keep</h2><h3 id="old">Gone heading</h3><p>Keep</p>',
        '<h2 id="x">Keep</h2><p>Keep</p>',
    )
    assert changed
    assert '<h3 class="wc-block-removed"><del>Gone heading</del></h3>' in body


def test_block_edit_in_a_cell_paragraph_is_marked_inside_its_one_row():
    body, _ = WHAT_CHANGED.diff_content(
        "<table><tr><td><p>one two</p></td><td>x</td></tr></table>",
        "<table><tr><td><p>one three</p></td><td>x</td></tr></table>",
    )
    assert _row_tags(body) == [
        "<tr><td><p>one <del>two</del><ins>three</ins></p></td><td>x</td></tr>"
    ]


def test_markup_that_does_not_nest_still_gets_the_word_diff():
    body, changed = WHAT_CHANGED.diff_content("<p>one<p>two", "<p>one<p>three")
    assert changed
    assert "<del>two</del><ins>three</ins>" in body


def test_diff_styles_are_one_palette_of_solid_red_and_green_in_light_and_dark():
    css = WHAT_CHANGED.DIFF_STYLE
    for name in ("block-added", "block-removed", "edit-new", "edit-old"):
        assert f".wc-{name}" in css
    assert ".wc-block-added ins" in css  # a whole added block: light shade only
    assert ".wc-link-changed" in css and ".wc-link-was" in css
    # Light: the block shade, then the words in it, one palette.
    for color in ("#dcf2d0", "#fcdad5", "#b4e4a0", "#f7b9b1", "#2a7a12", "#c41d2c"):
        assert color in css
    # Dark: solid shades, in the themed and standalone blocks.
    for var in ("--wc-ins-blk: #123a0e", "--wc-del-blk: #4a171b"):
        assert css.count(var) == 2
    assert "#1b4d0f" in css and "#6b1f22" in css  # the dark word marks
    # Solid colours only, no blue or orange pair, no neutral tint on an edit.
    assert "rgba(" not in css.split("--wc-changed")[0]
    assert "wc-edit-inline" not in css and "wc-edit-blk" not in css
    assert "wc-block-changed" not in css and "chg-blk" not in css


# What a themed page outside the workspace may set or select, as the engine's
# "Use from a page outside the workspace" lists it: each colour is set in light
# and in dark and used by a rule, and each mark has a rule.
STABLE_COLOURS = (
    "--wc-ins-bg",
    "--wc-del-bg",
    "--wc-ins-blk",
    "--wc-del-blk",
    "--wc-ins-line",
    "--wc-del-line",
    "--wc-changed",
    "--wc-new",
    "--wc-removed",
    "--wc-tag-fg",
)
STABLE_MARKS = (
    "ins",
    "del",
    ".wc-block-added",
    ".wc-block-removed",
    ".wc-edit-old",
    ".wc-edit-new",
)


def test_colour_variables_and_mark_classes_a_host_may_set_stay():
    css = ENGINE.DIFF_STYLE
    light = re.search(r"\.wc-scope \{(.*?)\}", css, re.S).group(1)
    dark = re.search(r'\[data-wc-mode="dark"\] \.wc-scope \{(.*?)\}', css, re.S)
    for name in STABLE_COLOURS:
        assert f"{name}:" in light and f"{name}:" in dark.group(1), name
        assert f"var({name})" in css, name
    for mark in STABLE_MARKS:
        assert re.search(rf"\.wc-scope [^{{]*{re.escape(mark)}\b", css), mark
    for name in STABLE_COLOURS + STABLE_MARKS:
        assert f"`{name}`" in ENGINE.__doc__, name


# Real-workspace defects: list items that go loose or tight, markup-only edits,
# wrapped blocks, math, and figures regenerated under their name.


def test_loose_item_edited_to_tight_pairs_and_diffs_its_words():
    body, changed = WHAT_CHANGED.diff_content(
        "<ul><li><p>Remotely, through gas2own: not testable from a branch.</p></li>"
        "<li><p>Second item stays.</p></li></ul>",
        "<ul><li>Remotely, through gas2own: not tested from a branch.</li>"
        "<li><p>Second item stays.</p></li></ul>",
    )
    assert changed
    assert "wc-block-removed" not in body and "wc-block-added" not in body
    # the item once, in its new shape, the removed word before the added one
    assert (
        "<li>Remotely, through gas2own: not <del>testable</del><ins>tested</ins>"
        " from a branch.</li>" in body
    )
    assert "<p>Second item stays.</p>" in body


def test_tight_item_edited_to_loose_pairs_and_diffs_its_words():
    body, changed = WHAT_CHANGED.diff_content(
        "<ul><li>Remotely, through gas2own: not testable from a branch.</li></ul>",
        "<ul><li><p>Remotely, through gas2own: not tested from a branch.</p></li></ul>",
    )
    assert changed
    assert "wc-block-removed" not in body and "wc-block-added" not in body
    # the item once, in its new shape (loose)
    assert (
        "<li><p>Remotely, through gas2own: not <del>testable</del><ins>tested</ins>"
        " from a branch.</p></li>" in body
    )


def test_loose_item_keeps_its_nested_list_when_it_goes_tight():
    body, changed = WHAT_CHANGED.diff_content(
        "<ul><li><p>One two</p><ul><li>a</li></ul></li></ul>",
        "<ul><li>One three<ul><li>a</li></ul></li></ul>",
    )
    assert changed
    assert "wc-block-removed" not in body
    # the item's text edited in place, with its nested list once
    assert "<li>One <del>two</del><ins>three</ins><ul><li>a</li></ul></li>" in body


@pytest.mark.parametrize(
    "old, new",
    [
        ("<li>First item.</li><li>Second item.</li>", "<li><p>First item.</p></li><li><p>Second item.</p></li>"),
        ("<li><p>First item.</p></li><li><p>Second item.</p></li>", "<li>First item.</li><li>Second item.</li>"),
    ],
)  # fmt: skip
def test_list_that_only_goes_tight_or_loose_shows_no_change(old, new):
    body, changed = WHAT_CHANGED.diff_content(f"<ul>{old}</ul>", f"<ul>{new}</ul>")
    assert not changed
    assert "<ins>" not in body and "<del>" not in body
    assert "wc-block" not in body


def test_formatting_only_change_marks_the_new_tag_not_the_words():
    body, changed = WHAT_CHANGED.diff_content(
        "<p>The result is <em>very important</em> for the paper.</p>",
        "<p>The result is <strong>very important</strong> for the paper.</p>",
    )
    assert changed
    assert re.search(
        r'<strong class="wc-fmt-changed"[^>]*>very important</strong>', body
    )
    assert "<ins>" not in body and "<del>" not in body


def test_formatting_taken_away_alone_shows_nothing():
    body, changed = WHAT_CHANGED.diff_content(
        "<p>The result is <em>very important</em> for the paper.</p>",
        "<p>The result is very important for the paper.</p>",
    )
    assert not changed
    assert "wc-block" not in body


def test_heading_level_change_with_the_same_text_pairs_and_shows_no_change():
    body, changed = WHAT_CHANGED.diff_content(
        "<h2>Methods and data</h2><p>Same.</p>", "<h3>Methods and data</h3><p>Same.</p>"
    )
    assert not changed
    assert body == "<h3>Methods and data</h3><p>Same.</p>"


def test_heading_level_change_with_an_edit_diffs_the_words():
    body, changed = WHAT_CHANGED.diff_content(
        "<h2>Methods and data used</h2>", "<h3>Methods and data gathered</h3>"
    )
    assert changed
    # drawn once, at its new level
    assert body == "<h3>Methods and data <del>used</del><ins>gathered</ins></h3>"


def test_paragraph_wrapped_in_a_new_div_pairs_with_its_old_self():
    old = "<p>A short paragraph with seven words in it today.</p>"
    body, changed = WHAT_CHANGED.diff_content(old, f'<div class="callout">{old}</div>')
    assert not changed
    assert body == f'<div class="callout">{old}</div>'
    body, changed = WHAT_CHANGED.diff_content(f'<div class="callout">{old}</div>', old)
    assert not changed
    assert body == old


def test_wrapped_paragraph_with_an_edit_diffs_the_words_inside_the_wrapper():
    body, changed = WHAT_CHANGED.diff_content(
        "<p>A short paragraph with seven words in it today.</p>",
        '<div class="callout"><p>A short paragraph with eight words in it today.</p></div>',
    )
    assert changed
    assert body == (
        '<div class="callout">'
        "<p>A short paragraph with <del>seven</del><ins>eight</ins> words in it today.</p>"
        "</div>"
    )


MATH_OLD = '<p>Let <span class="math inline">\\(x^2 + y\\)</span> be small.</p>'
MATH_NEW = '<p>Let <span class="math inline">\\(x^3 + y\\)</span> be small.</p>'


def test_edited_inline_equation_is_old_in_red_then_new_in_green_as_whole_units():
    body, changed = WHAT_CHANGED.diff_content(MATH_OLD, MATH_NEW)
    assert changed
    assert (
        '<p>Let <del class="wc-unit">'
        '<span class="math inline">\\(x^2 + y\\)</span></del>'
        '<ins class="wc-unit">'
        '<span class="math inline">\\(x^3 + y\\)</span></ins> be small.</p>'
    ) == body
    assert "wcunit" not in body
    # no mark inside either equation's TeX
    for span in re.findall(r'<span class="math[^>]*>.*?</span>', body):
        assert "<ins>" not in span and "<del>" not in span


def test_edited_display_equation_is_compared_whole():
    old = '<p>So <span class="math display">\\[a = b + c\\]</span></p>'
    new = '<p>So <span class="math display">\\[a = b + d\\]</span></p>'
    body, changed = WHAT_CHANGED.diff_content(old, new)
    assert changed
    assert (
        '<del class="wc-unit"><span class="math display">\\[a = b + c\\]</span></del>'
        in body
    )
    assert (
        '<ins class="wc-unit"><span class="math display">\\[a = b + d\\]</span></ins>'
        in body
    )


def test_equation_touching_punctuation_changes_alone():
    body, _ = WHAT_CHANGED.diff_content(
        '<p>(<span class="math inline">\\(a\\)</span>), then.</p>',
        '<p>(<span class="math inline">\\(b\\)</span>), then.</p>',
    )
    assert (
        '>(<del class="wc-unit"><span class="math inline">\\(a\\)</span></del>' in body
    )
    assert "</ins>), then.</p>" in body


def test_unchanged_equation_beside_an_edited_word_is_left_alone():
    body, changed = WHAT_CHANGED.diff_content(
        '<p>Let <span class="math inline">\\(x\\)</span> be small.</p>',
        '<p>Let <span class="math inline">\\(x\\)</span> be large.</p>',
    )
    assert changed
    assert (
        'Let <span class="math inline">\\(x\\)</span> be <del>small.</del><ins>large.</ins>'
        in body
    )
    assert "wc-unit" not in body


def test_added_and_removed_equations_are_whole_units():
    eq = '<span class="math inline">\\(z\\)</span>'
    body, _ = WHAT_CHANGED.diff_content("<p>Sum.</p>", f"<p>Sum. {eq}</p>")
    assert f'<ins class="wc-unit">{eq}</ins>' in body
    body, _ = WHAT_CHANGED.diff_content(f"<p>Sum. {eq}</p>", "<p>Sum.</p>")
    assert f'<del class="wc-unit">{eq}</del>' in body


def _images(digests, urls=None):
    class Images:
        def __call__(self, side, src):
            return digests.get((side, src))

        def before_url(self, src):
            return (urls or {}).get(src)

    return Images()


def test_regenerated_figure_shows_before_and_after():
    page = '<p><img src="plot.png" alt="Plot"></p><p>Figure 1: scores.</p>'
    images = _images(
        {("old", "plot.png"): "aaaa", ("new", "plot.png"): "bbbb"},
        {"plot.png": "data:image/png;base64,OLD"},
    )
    body, changed = WHAT_CHANGED.diff_content(page, page, images)
    assert changed
    # in the one paragraph, the old figure (light red) then the new (light green)
    assert (
        '<p><del class="wc-unit"><img src="data:image/png;base64,OLD" alt="Plot"></del>'
        '<ins class="wc-unit"><img src="plot.png" alt="Plot"></ins></p>'
    ) in body
    assert "data-wc-digest" not in body
    assert "<p>Figure 1: scores.</p>" in body  # the caption is untouched


def test_regenerated_figure_with_a_new_alt_still_shows_the_old_bytes_as_removed():
    images = _images(
        {("old", "plot.png"): "aaaa", ("new", "plot.png"): "bbbb"},
        {"plot.png": "data:image/png;base64,OLD"},
    )
    body, changed = WHAT_CHANGED.diff_content(
        '<p><img src="plot.png" alt="Old plot" width="300"></p>',
        '<p><img src="plot.png" alt="New plot" width="500"></p>',
        images,
    )
    assert changed
    assert (
        '<del class="wc-unit"><img src="data:image/png;base64,OLD" alt="Old plot" '
        'width="300"></del>'
    ) in body
    assert (
        '<ins class="wc-unit"><img src="plot.png" alt="New plot" width="500">' in body
    )
    assert "data-wc-digest" not in body


def test_old_figure_drawn_from_its_old_bytes_has_no_srcset_sizes_or_picture_source():
    # With srcset a browser picks from it and ignores src, which would show the
    # new site's file where the old bytes belong; the sanitizer that diff_content
    # runs keeps none of srcset, sizes or a picture's source.
    page = (
        '<p><picture><source srcset="plot-2x.png 2x" type="image/png">'
        '<img src="plot.png" srcset="plot.png 1x, plot-2x.png 2x" sizes="50vw" '
        'alt="Plot"></picture></p>'
    )
    images = _images(
        {("old", "plot.png"): "aaaa", ("new", "plot.png"): "bbbb"},
        {"plot.png": "data:image/png;base64,OLD"},
    )
    body, _ = WHAT_CHANGED.diff_content(page, page, images)
    old = re.search(r'<del class="wc-unit">(<img [^>]*>)</del>', body).group(1)
    assert old == '<img src="data:image/png;base64,OLD" alt="Plot">'
    new = re.search(r'<ins class="wc-unit">(<img [^>]*>)</ins>', body).group(1)
    assert new == '<img src="plot.png" alt="Plot">'
    assert not re.search(r"srcset|sizes|<source|<picture", body)


def test_removed_figure_with_a_srcset_drops_it_too():
    images = _images(
        {("old", "gone.png"): "aaaa"}, {"gone.png": "data:image/png;base64,OLD"}
    )
    body, _ = WHAT_CHANGED.diff_content(
        '<p><img src="gone.png" srcset="gone.png 1x, gone-2x.png 2x" sizes="5em"></p>',
        "<p>Text.</p>",
        images,
    )
    assert '<img src="data:image/png;base64,OLD">' in body
    assert "srcset" not in body and "sizes" not in body


def test_removed_figure_only_the_old_site_has_shows_its_old_bytes():
    images = _images(
        {("old", "gone.png"): "aaaa"}, {"gone.png": "data:image/png;base64,OLD"}
    )
    body, _ = WHAT_CHANGED.diff_content(
        '<p>See <img src="gone.png" alt="Gone"> here.</p>', "<p>See here.</p>", images
    )
    assert '<del class="wc-unit"><img src="data:image/png;base64,OLD"' in body
    assert 'src="gone.png"' not in body


def test_old_figure_that_cannot_be_inlined_is_said_so_not_shown_as_the_new_one():
    images = _images({("old", "plot.png"): "aaaa", ("new", "plot.png"): "bbbb"})
    body, changed = WHAT_CHANGED.diff_content(
        '<p><img src="plot.png" alt="Old plot"></p>',
        '<p><img src="plot.png" alt="New plot"></p>',
        images,
    )
    assert changed
    (removed,) = re.findall(r"<del class=\"wc-unit\">(.*?)</del>", body)
    assert "<img" not in removed
    assert "wc-img-unavailable" in removed and "Old plot" in removed
    assert '<ins class="wc-unit"><img src="plot.png" alt="New plot">' in body


def test_removed_figure_with_the_same_bytes_on_both_sites_keeps_its_name():
    images = _images({("old", "plot.png"): "aaaa", ("new", "plot.png"): "aaaa"})
    body, _ = WHAT_CHANGED.diff_content(
        '<p>Plot <img src="plot.png" alt="Plot"></p>', "<p>Plot</p>", images
    )
    assert '<del class="wc-unit"><img src="plot.png" alt="Plot"></del>' in body


def test_figure_with_the_same_bytes_is_no_change():
    page = '<p><img src="plot.png" alt="Plot"></p>'
    images = _images({("old", "plot.png"): "aaaa", ("new", "plot.png"): "aaaa"})
    body, changed = WHAT_CHANGED.diff_content(page, page, images)
    assert not changed
    assert body == page


def test_image_with_no_known_digest_is_not_called_changed():
    page = '<p><img src="https://example.org/p.png"></p>'
    body, changed = WHAT_CHANGED.diff_content(page, page, _images({}))
    assert not changed
    assert body == page


def test_regenerated_figure_inside_a_quarto_figure_block():
    page = (
        '<div class="quarto-figure"><figure class="figure"><p>'
        '<img src="fig.png" class="img-fluid figure-img"></p>'
        "<figcaption>Scores by model.</figcaption></figure></div>"
    )
    images = _images(
        {("old", "fig.png"): "1", ("new", "fig.png"): "2"},
        {"fig.png": "data:image/png;base64,OLD"},
    )
    body, changed = WHAT_CHANGED.diff_content(page, page, images)
    assert changed
    assert '<del class="wc-unit"><img' in body
    assert '<ins class="wc-unit"><img' in body
    assert "<figcaption>Scores by model.</figcaption>" in body


def test_page_with_a_regenerated_figure_is_shown_though_its_html_is_the_same(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for root, data in ((old, b"\x89PNG-old"), (new, b"\x89PNG-new")):
        root.mkdir()
        (root / "plot.png").write_bytes(data)
        (root / "index.html").write_text(
            '<main><p><img src="plot.png" alt="Plot"></p><p>Figure 1.</p></main>'
        )

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert '<del class="wc-unit"><img' in result
    assert '<ins class="wc-unit"><img' in result
    assert "data:image/png;base64," in result  # the old file, inlined
    assert "1 page changed" in result


def _code(text):
    return f'<pre class="sourceCode"><code class="sourceCode">{text}</code></pre>'


def _sides(body):
    """The text of a diff as the old page had it (outside <ins>) and the new
    page (outside <del>), tags dropped."""
    old = re.sub(r"<ins\b[^>]*>.*?</ins>", "", body, flags=re.S)
    new = re.sub(r"<del\b[^>]*>.*?</del>", "", body, flags=re.S)
    return tuple(html.unescape(re.sub(r"<[^>]+>", "", t)) for t in (old, new))


@pytest.mark.parametrize(
    "old, new",
    [
        ("if ok:\n    publish()\n", "if ok:\npublish()\n"),  # dedented
        ("a = 1\nb = 2\n", "a = 1 b = 2\n"),  # a line break became a space
        ("x\n\n\ny\n", "x\n\ny\n"),  # a blank line removed
        ("\tx = 1\n", "    x = 1\n"),  # a tab became spaces
    ],
)
def test_whitespace_inside_a_code_block_is_a_change_shown_exactly(old, new):
    body, changed = WHAT_CHANGED.diff_content(_code(old), _code(new))
    assert changed
    assert "<ins>" in body and "<del>" in body
    assert _sides(body) == (old, new)


def test_whitespace_outside_code_is_still_not_a_change():
    body, changed = WHAT_CHANGED.diff_content(
        "<p>a  b\n c</p><pre><code>x\n</code></pre>",
        "<p>a b c</p><pre><code>x\n</code></pre>",
    )
    assert not changed
    assert "<ins>" not in body and "<del>" not in body


def test_phrase_changed_inside_code_is_one_mark_on_each_side():
    body, _ = WHAT_CHANGED.diff_content(_code("run(a, b)\n"), _code("run(c, d)\n"))
    assert _sides(body) == ("run(a, b)\n", "run(c, d)\n")


def test_page_whose_only_change_is_code_whitespace_is_shown(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for root, code in ((old, "if ok:\n    publish()\n"), (new, "if ok:\npublish()\n")):
        root.mkdir()
        (root / "index.html").write_text(f"<main><p>Run it.</p>{_code(code)}</main>")

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert "1 page changed" in result
    assert "non-visible markup" not in result
    assert "<del>    </del>" in result or "<del>\n    </del>" in result


def test_slide_whose_only_change_is_its_figure_file_is_shown(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    deck = (
        '<html><head><link rel="stylesheet" href="site_libs/revealjs/reveal.css">'
        '</head><body><div class="reveal"><div class="slides"><section>'
        '<h2>Results</h2><p><img src="plot.png" alt="Plot"></p></section></div>'
        "</div></body></html>"
    )
    for root, data in ((old, b"\x89PNG-old"), (new, b"\x89PNG-new")):
        root.mkdir()
        (root / "plot.png").write_bytes(data)
        (root / "slides.html").write_text(deck)

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert "1 page changed" in result
    assert '<del class="wc-unit"><img' in result
    assert '<ins class="wc-unit"><img' in result


def test_page_whose_figure_file_is_unchanged_is_not_shown(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for root in (old, new):
        root.mkdir()
        (root / "plot.png").write_bytes(b"\x89PNG-same")
        (root / "index.html").write_text('<main><p><img src="plot.png"></p></main>')

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert "No rendered content changed" in result


def test_site_images_stay_inside_the_site_root(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for root in (old, new):
        root.mkdir()
    (tmp_path / "outside.png").write_bytes(b"x")
    (new / "in.png").write_bytes(b"y")
    images = WHAT_CHANGED.SiteImages(old, new)
    assert images("new", "in.png")
    assert images("new", "../outside.png") is None
    assert images("new", "https://example.org/in.png") is None
    assert images("old", "in.png") is None


def test_the_table_of_kinds_has_these_roles():
    roles = {kind.role for kind in ENGINE.KINDS}
    assert roles == {"text", "row", "container", "inline", "unit"}


def _text_of(html_):
    return re.sub(r"<[^>]+>", "", html_)


def test_source_diff_numbers_lines_and_shades_like_blocks():
    old = "a = 1\nb = foo(x, y)\n# removed\nend\n"
    new = "a = 1\nb = foo(x, y, w)\nsomething_else()\nend\n"
    out = ENGINE.source_diff(old, new)
    # An unchanged line has both numbers and no mark.
    assert '<div class="wc-ln" data-o="1" data-n="1">a = 1</div>' in out
    # A paired, edited line is two rows, as GitHub's unified view draws it: the
    # old line (light red, its old number only), then the new line (light green,
    # its new number only), each with its own words darker.
    assert (
        '<div class="wc-ln wc-edit-old" data-o="2">b = foo(x, y)</div>'
        '<div class="wc-ln wc-edit-new" data-n="2">b = foo(x, y<ins>, w</ins>)</div>'
    ) in out
    # A line too different to pair is removed whole (old number only) and added
    # whole (new number only): light on the line, no darker words on top.
    assert '<div class="wc-ln wc-block-removed" data-o="3"><del>' in out
    assert '<div class="wc-ln wc-block-added" data-n="3"><ins>' in out
    assert '<div class="wc-ln" data-o="4" data-n="4">end</div>' in out


def test_source_diff_escapes_and_keeps_indentation_and_blank_lines():
    out = ENGINE.source_diff("if a < b:\n  x\n\ny\n", "if a < b:\n    x\ny\n")
    assert "a &lt; b:" in out and "<b" not in out
    # An indentation change is a change: the old row has the old whitespace
    # darker, the new row the new.
    assert 'wc-edit-old" data-o="2"><del>  </del>x</div>' in out
    assert 'wc-edit-new" data-n="2"><ins>    </ins>x</div>' in out
    # A removed blank line is a removed line, so the numbers stay right.
    assert 'wc-block-removed" data-o="3"' in out
    assert 'data-o="4" data-n="3">y<' in out.replace("</div>", "<")


def test_source_diff_of_equal_texts_has_no_marks():
    out = ENGINE.source_diff("a\nb\n", "a\nb\n")
    assert "<ins>" not in out and "<del>" not in out
    assert _text_of(out) == "ab"


def test_source_diff_pairs_by_the_shared_engine_not_by_position():
    # A line inserted above does not make every line below it a change.
    old = "\n".join(f"line number {i} here" for i in range(30))
    new = "brand new first\n" + old
    out = ENGINE.source_diff(old, new)
    assert out.count("<ins>") >= 1
    assert out.count("wc-block-added") == 1
    assert "wc-block-removed" not in out and "wc-edit" not in out


def test_source_lines_are_a_kind_of_the_one_table():
    assert ENGINE.role_of("wc-ln") == "text"
    assert "wc-ln" in ENGINE.TINT_BLOCKS


def test_one_stylesheet_and_one_fold_strip_serve_both_inputs():
    css, js = WHAT_CHANGED.DIFF_STYLE, WHAT_CHANGED.FOLD_JS
    for name in ("wc-ln", "wc-src", "wc-strip", "--wc-strip", "wc-block-added"):
        assert name in css
    # The one strip names what it hides, opens about 20 at a time, opens all.
    assert 'var name = lines ? "line" : nameOf(el)' in js
    assert "var STEP = 20" in js and "Show all" in js
    assert 'createElement("details")' not in js


# A page outside the workspace loads the raw file by path and uses its public
# pieces; these keep that contract (see the header of diff-engine.py).


def _load_like_an_outside_page(tmp_path):
    copy = tmp_path / "diff-engine.py"
    copy.write_text(ENGINE_SCRIPT.read_text())
    spec = importlib.util.spec_from_file_location("outside_diff_engine", copy)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _selectors(css):
    """Every selector of a stylesheet, inside @media too, split on top-level commas."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    out, depth, start = [], 0, 0
    for i, ch in enumerate(css):
        if ch == "{":
            head = css[start:i].strip()
            if not head.startswith("@"):
                level, piece = 0, ""
                for c in head:
                    if c == "," and level == 0:
                        out.append(piece.strip())
                        piece = ""
                        continue
                    level += c in "([" and 1 or -(c in ")]")
                    piece += c
                out.append(piece.strip())
            start = i + 1
            depth += 1
        elif ch == "}":
            start = i + 1
            depth -= 1
    return out


def test_outside_page_gets_fragments_from_both_entry_points(tmp_path):
    wc = _load_like_an_outside_page(tmp_path)
    page, changed = wc.diff_content(
        "<p>The method is fast.</p><p>Same.</p>",
        "<p>The method is slow and exact.</p><p>Same.</p>",
    )
    assert changed is True
    source = wc.source_diff("a = 1\nb = 2\n", "a = 1\nb = 3\n")
    for fragment in (page, source):
        assert isinstance(fragment, str) and "<ins" in fragment and "<del" in fragment
        assert not re.search(r"<(html|head|body)\b", fragment, re.I)
    assert "wc-src" in source
    assert wc.FOLD_JS.strip()


def test_the_documented_outside_page_wrapper_is_the_one_the_fold_script_selects():
    # The DOM test (tests/dom) runs it; here the header and the script agree.
    assert '<div class="wc-scope wc-standalone" data-wc-fold>' in ENGINE.__doc__
    assert "[data-wc-fold]" in ENGINE.FOLD_JS


def test_muted_text_borrows_the_hosts_own_text_colour_when_it_has_no_theme():
    # On a dark host page without Bootstrap's --bs-secondary-color a fixed grey
    # (#57606a) is 2.5:1 on #222; the host's text colour, thinned, is not.
    css = WHAT_CHANGED.DIFF_STYLE
    rule = re.search(r"\.wc-scope \{.*?\}", css, re.S).group(0)
    assert re.search(
        r"--wc-muted:\s*var\(--bs-secondary-color,\s*"
        r"color-mix\(in srgb, currentColor 70%, transparent\)\)",
        rule,
    )
    # a page with no theme at all keeps its own greys
    standalone = re.search(r"\.wc-scope\.wc-standalone \{[^}]*\}", css).group(0)
    assert "--wc-muted: #57606a" in standalone


@pytest.mark.parametrize("name", ["DIFF_STYLE", "STANDALONE_STYLE"])
def test_every_style_selector_is_scoped_under_wc_scope(tmp_path, name):
    selectors = _selectors(getattr(_load_like_an_outside_page(tmp_path), name))
    assert selectors
    assert [s for s in selectors if ".wc-scope" not in s] == []


def test_module_imports_only_the_standard_library():
    import ast

    tree = ast.parse(ENGINE_SCRIPT.read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import needs a package"
            modules.add(node.module.split(".")[0])
    assert modules
    assert sorted(m for m in modules if m not in sys.stdlib_module_names) == []


# The old copy of an edited block keeps its own inline structure (review of
# 0d50bd36): both copies stay valid HTML with their links and formatting.


def _nests(fragment):
    """Whether every non-void tag of `fragment` is closed by its own end tag."""
    from html.parser import HTMLParser

    void = {"br", "img", "wbr", "hr", "input", "meta", "link", "source", "col"}

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.ok = [], True

        def handle_starttag(self, tag, attrs):
            if tag not in void:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if not self.stack or self.stack.pop() != tag:
                self.ok = False

    p = P()
    p.feed(fragment)
    return p.ok and not p.stack


def _removed(body):
    """The words the page lost: everything inside its `<del>` marks."""
    return "".join(re.findall(r"<del\b.*?</del>", body, re.S))


def test_edited_block_keeps_the_formatting_it_has():
    body, _ = WHAT_CHANGED.diff_content(
        "<p><em>alpha beta gamma</em></p>", "<p>alpha <em>beta delta</em></p>"
    )
    assert body == (
        '<p>alpha <em class="wc-fmt-changed" title="formatting changed">'
        "beta <del>gamma</del><ins>delta</ins></em></p>"
    )
    assert _nests(body)


@pytest.mark.parametrize(
    "markup", ['<a href="x">alpha beta</a>', "<em>alpha beta</em>"]
)
def test_removed_words_keep_the_link_and_formatting_they_had(markup):
    body, _ = WHAT_CHANGED.diff_content(f"<p>see {markup} end</p>", "<p>see end</p>")
    assert _removed(body) == f"<del>{markup} </del>"
    assert _nests(body)


@pytest.mark.parametrize(
    "new_link, href",
    [
        ('<a href="x">beta gamma</a> new', "x"),
        ('beta <a href="y">gamma</a> new', "y"),
    ],
)
def test_link_whose_boundary_moved_stays_one_valid_link(new_link, href):
    body, _ = WHAT_CHANGED.diff_content(
        '<p>see <a href="x">alpha beta</a> gamma old</p>',
        f"<p>see alpha {new_link}</p>",
    )
    assert f'<a href="{href}">' in body
    assert body.count("<a ") == body.count("</a>") == 1
    assert "<del>gamma old</del>" in body
    assert _nests(body)


# Ids stay unique on the page: the removed words carry none (the new page owns
# them).


def _ids(fragment, name):
    return re.findall(rf'\bid="{name}"', fragment)


def _loses(markup):
    """An old page with `markup` in a paragraph, and a new one without it that
    has a heading take over its id."""
    return (
        f"<p>Shared {markup} words</p>",
        '<p>Shared words</p><h2 id="ref">Elsewhere</h2>',
    )


@pytest.mark.parametrize(
    "markup",
    [
        '<a id="ref" href="#ref">link</a>',
        '<span id="ref">shared</span>',
        '<span class="math inline" id="ref">\\(x^2\\)</span>',
        '<span class="ev" role="note">claim<span class="ev-pop" id="ref">q</span>'
        "</span>",
    ],
)
def test_removed_words_carry_no_ids_inline_or_restored(markup):
    body, changed = WHAT_CHANGED.diff_content(*_loses(markup))
    assert changed
    assert _ids(body, "ref") == ['id="ref"']  # the heading's
    assert not _ids(_removed(body), "ref")
    # kept in an edited paragraph, it is the one id there is
    body, changed = WHAT_CHANGED.diff_content(
        f"<p>Shared {markup} old words</p>", f"<p>Shared {markup} new words</p>"
    )
    assert changed
    assert _ids(body, "ref") == ['id="ref"']


def test_removed_block_drops_the_ids_inside_it_too():
    body, _ = WHAT_CHANGED.diff_content(
        '<p>Keep this paragraph.</p><p>Gone <a id="ref" href="#ref">link</a> text</p>',
        '<p>Keep this paragraph.</p><h2 id="ref">Elsewhere</h2>',
    )
    assert "wc-block-removed" in body
    assert _ids(body, "ref") == ['id="ref"']
    assert re.search(r'<h2[^>]* id="ref"', body)


@pytest.mark.parametrize(
    "tag", ['<a id="%s" href="/docs">', '<span id="%s" class="note">']
)
def test_a_renamed_inline_id_alone_is_not_a_change(tag):
    close = "</a>" if tag.startswith("<a") else "</span>"
    body, changed = WHAT_CHANGED.diff_content(
        f"<p>See {tag % 'one'}the docs{close} here.</p>",
        f"<p>See {tag % 'two'}the docs{close} here.</p>",
    )
    assert not changed
    assert "wc-link" not in body and "<ins>" not in body and "<del>" not in body


# A cell only one side has, empty or not, is kept where it is in the one row.


@pytest.mark.parametrize(
    "old_cells, new_cells",
    [
        ("<td>shared old</td><td>x</td>", "<td>shared new</td><td></td><td>x</td>"),
        ("<td>shared old</td><td></td><td>x</td>", "<td>shared new</td><td>x</td>"),
        (
            "<td>shared old</td><td>x</td>",
            '<td>shared new</td><td colspan="2"></td><td>x</td>',
        ),
        (
            '<td>shared old</td><td colspan="3"></td><td>x</td>',
            "<td>shared new</td><td>x</td>",
        ),
    ],
)
def test_an_empty_cell_only_one_side_has_stays_in_the_one_row(old_cells, new_cells):
    body, changed = WHAT_CHANGED.diff_content(
        f"<table><tr>{old_cells}</tr></table>", f"<table><tr>{new_cells}</tr></table>"
    )
    assert changed
    (row,) = _row_tags(body)  # one row, the cells of the new page, the words marked
    assert "<td>shared <del>old</del><ins>new</ins></td>" in row
    assert row.endswith("<td>x</td></tr>")
    assert re.sub(r"<[^>]+>", "", row).count("x") == 1
    assert "wc-edit" not in body and "wc-gap" not in body
    assert _nests(body)


# A small edit on a long generated page stays fast: the block alignment is bound
# as the word matcher is (common ends trimmed, repetitive middles guarded).


def _repeated(first, last, count=12_000):
    return f"<p>{first}</p>" + "<p>shared content</p>" * count + f"<p>{last}</p>"


def test_small_edit_on_thousands_of_repeated_blocks_is_fast():
    import time

    old, new = _repeated("first one", "last one"), _repeated("first two", "last two")
    start = time.perf_counter()
    body, changed = WHAT_CHANGED.diff_content(old, new)
    assert time.perf_counter() - start < 2  # 15.7 s before the bound
    assert changed
    assert body.count("<ins>") == body.count("<del>") == 2  # not a wholesale rewrite
    assert body.count("wc-block") == 0  # two edited blocks, no shade on either


def test_many_similar_edited_blocks_are_paired_without_cubic_work():
    import time

    def page(word):
        return "".join(
            f"<p>{i} alpha beta gamma delta epsilon zeta eta {word}.</p>"
            for i in range(240)
        )

    start = time.perf_counter()
    body, changed = WHAT_CHANGED.diff_content(page("old"), page("new"))
    assert time.perf_counter() - start < 2  # 8.5 s when every pick rescanned all pairs
    assert changed
    assert body.count("<ins>new.</ins>") == body.count("<del>old.</del>") == 240
    assert body.count("wc-block") == 0  # every paragraph one edited block


def test_repeated_blocks_within_the_bound_still_align_exactly():
    body, changed = WHAT_CHANGED.diff_content(
        _repeated("first one", "last one", 300), _repeated("first two", "last two", 300)
    )
    assert changed
    assert body.count("<ins>") == body.count("<del>") == 2  # the two edits only
    assert body.count("<p>shared content</p>") == 300  # all unchanged, none marked


def test_edits_at_the_ends_of_a_long_page_do_not_cost_the_middle():
    import time

    middle = "".join(f"<p>block number {i} stays</p>" for i in range(20_000))
    start = time.perf_counter()
    body, _ = WHAT_CHANGED.diff_content(
        f"<p>top old</p>{middle}", f"<p>top new</p>{middle}<p>appended</p>"
    )
    assert time.perf_counter() - start < 2
    assert body.startswith("<p>top <del>old</del><ins>new</ins></p>")
    assert body.count("wc-block-added") == 1


def test_one_more_repeated_block_is_one_insertion_not_a_rewrite():
    body, changed = WHAT_CHANGED.diff_content(
        _repeated("same", "end", 12_000), _repeated("same", "end", 12_001)
    )
    assert changed
    assert body.count("wc-block-added") == 1 and "wc-block-removed" not in body


def test_run_compressed_alignment_tiles_both_lists(monkeypatch):
    import random

    monkeypatch.setattr(ENGINE, "ALIGN_CANDIDATES", 0)  # always compress runs
    rng = random.Random(7)
    for _ in range(300):
        a = [rng.choice("abc") for _ in range(rng.randrange(0, 14))]
        b = [rng.choice("abc") for _ in range(rng.randrange(0, 14))]
        i = j = 0
        for op, i1, i2, j1, j2 in ENGINE._align(a, b):
            assert (i1, j1) == (i, j), (a, b)
            if op == "equal":
                assert a[i1:i2] == b[j1:j2] and i2 > i1
            i, j = i2, j2
        assert (i, j) == (len(a), len(b))


def _all_ids(fragment, name):
    """Every `id` attribute of `fragment` that names `name`, quoted or not."""
    return re.findall(rf"""\sid\s*=\s*["']?{name}\b""", fragment)


def test_a_moved_unit_keeps_its_id_in_the_new_place():
    u = '<span class="math inline" id="eq">\\(x^2\\)</span>'
    body, changed = WHAT_CHANGED.diff_content(
        f"<p>Original intro</p><p>Middle stable words</p><p>Original equation {u}</p>",
        f"<p>Original equation {u}</p><p>Original intro</p><p>Middle stable words</p>",
    )
    assert changed
    added = re.search(r'<p class="wc-block-added">.*?</p>', body, re.S).group(0)
    removed = re.search(r'<p class="wc-block-removed">.*?</p>', body, re.S).group(0)
    # a link to #eq lands on the current equation, never the struck one
    assert _all_ids(added, "eq") and not _all_ids(removed, "eq")


def test_equation_whose_only_change_is_its_id_is_no_change():
    old = '<p>Sum <span class="math inline" id="eq-old">\\(x^2\\)</span> done.</p>'
    new = '<p>Sum <span class="math inline" id="eq-new">\\(x^2\\)</span> done.</p>'
    body, changed = WHAT_CHANGED.diff_content(old, new)
    assert not changed
    assert body == new  # the new page's fragment, with its id


def test_display_equation_paragraph_with_a_new_id_is_not_removed_and_added():
    old = '<p><span class="math display" id="a1">\\[x\\]</span></p>'
    new = '<p><span class="math display" id="a2">\\[x\\]</span></p>'
    body, changed = WHAT_CHANGED.diff_content(old, new)
    assert not changed
    assert "wc-block" not in body and "<ins" not in body and "<del" not in body


def test_two_equations_with_the_same_tex_keep_their_own_ids():
    def page(a, b):
        return (
            f'<p>One <span class="math inline" id="{a}">\\(x\\)</span> and '
            f'two <span class="math inline" id="{b}">\\(x\\)</span>.</p>'
        )

    body, changed = WHAT_CHANGED.diff_content(page("e1", "e2"), page("f1", "f2"))
    assert not changed
    assert body == page("f1", "f2")


def test_evidence_popover_whose_only_change_is_its_id_is_no_change():
    def page(ident):
        return (
            '<p>Kosmos averages <span class="ev" role="note">42,000'
            f'<span class="ev-pop" role="note" id="{ident}"><span class="ev-card">'
            '<span class="ev-quote">an average of 42,000</span></span></span>'
            "</span> per run.</p>"
        )

    body, changed = WHAT_CHANGED.diff_content(page("pop-1"), page("pop-2"))
    assert not changed
    assert "evidence added" not in body and "evidence removed" not in body
    assert body == page("pop-2")


@pytest.mark.parametrize("quote", ['"', "'", ""])
def test_removed_words_carry_no_ids_however_they_are_quoted(quote):
    ident = f"id={quote}ref{quote}"
    body, changed = WHAT_CHANGED.diff_content(
        *_loses(f'<a {ident} href="#ref">link</a>')
    )
    assert changed
    assert len(_all_ids(body, "ref")) == 1  # the heading's
    assert not _all_ids(_removed(body), "ref")
    # kept in an edited paragraph, it is the one id there is
    body, changed = WHAT_CHANGED.diff_content(
        f'<p>Shared <a {ident} href="#ref">link</a> old words</p>',
        f'<p>Shared <a {ident} href="#ref">link</a> new words</p>',
    )
    assert changed
    assert len(_all_ids(body, "ref")) == 1


@pytest.mark.parametrize(
    "markup",
    [
        "<span class=math id=ref>\\(x^2\\)</span>",
        "<span class='math inline' id='ref'>\\(x^2\\)</span>",
        '<span class="ev" role="note">claim<span class="ev-pop" id=ref>q</span></span>',
    ],
)
def test_restored_units_drop_unquoted_ids_in_the_removed_words(markup):
    body, changed = WHAT_CHANGED.diff_content(*_loses(markup))
    assert changed
    assert len(_all_ids(body, "ref")) == 1  # the heading's
    assert not _all_ids(_removed(body), "ref")
    body, changed = WHAT_CHANGED.diff_content(
        f"<p>Shared {markup} old words</p>", f"<p>Shared {markup} new words</p>"
    )
    assert changed
    assert len(_all_ids(body, "ref")) == 1


_IDLIKE_TEXT = [
    'title="Set id=3 for the user"',
    "title='Set id=3 for the user'",
    'aria-label="Set id = 3 for the user"',
    "aria-label='Set id=3 for the user'",
    "title=\"Set id='3' for the user\"",
]


def _opened(attr):
    """The open tag of `<a {attr} href="#ref">` as the sanitizer, which
    diff_content runs first, writes it (its attributes quoted one way)."""
    return ENGINE.sanitize_fragment(f'<a {attr} href="#ref">')


@pytest.mark.parametrize("attr", _IDLIKE_TEXT)
def test_edited_block_keeps_id_like_text_inside_other_attributes(attr):
    body, changed = WHAT_CHANGED.diff_content(
        f'<p>Shared <a {attr} href="#ref">link</a> old words</p>',
        f'<p>Shared <a {attr} href="#ref">link</a> new words</p>',
    )
    assert changed
    assert _opened(attr) in body


@pytest.mark.parametrize("attr", _IDLIKE_TEXT)
@pytest.mark.parametrize("ident", ['id="ref"', "id='ref'", "id=ref"])
def test_removed_words_drop_only_the_real_id_beside_id_like_text(attr, ident):
    body, changed = WHAT_CHANGED.diff_content(
        *_loses(f'<a {attr} {ident} href="#ref">link</a>')
    )
    assert changed
    assert _opened(attr) in _removed(body)
    assert not _all_ids(_removed(body), "ref")
    assert len(_all_ids(body, "ref")) == 1  # the heading's


@pytest.mark.parametrize("ident", ["", ' id="ref"', " id=ref"])
def test_restored_units_keep_id_like_text_in_other_attributes(ident):
    unit = (
        f'<span class="math inline" title="Set id=3 for the user"{ident}>'
        "\\(x^2\\)</span>"
    )
    body, changed = WHAT_CHANGED.diff_content(*_loses(unit))
    assert changed
    assert 'title="Set id=3 for the user"' in _removed(body)
    assert not _all_ids(_removed(body), "ref")


def test_prose_that_looks_like_an_id_is_still_a_change():
    body, changed = WHAT_CHANGED.diff_content(
        "<p>Set id=3 for the user.</p>", "<p>Set id=4 for the user.</p>"
    )
    assert changed


# An edited block on a rendered page is drawn once, inline: the removed words
# struck right before the added ones, no tint on the block.


def _ids_unique(body):
    ids = re.findall(r'\sid="([^"]*)"', body)
    return len(ids) == len(set(ids))


def _words_of(body, side):
    """The visible words of one side: unmarked and `side`'s marked words."""
    drop = "ins" if side == "old" else "del"
    body = re.sub(rf"<{drop}[^>]*>.*?</{drop}>", "", body, flags=re.S)
    return re.sub(r"<[^>]+>", " ", body).split()


EDITED_PARA = (
    '<p id="intro">The model is fast and cheap to run today.</p>',
    '<p id="intro">The model is slow and cheap to run today.</p>',
)
REWRITTEN_PARA = (
    "<p>Alpha beta gamma delta epsilon zeta.</p>",
    "<p>Alpha eta gamma iota kappa zeta.</p>",
)


def test_edited_paragraph_is_drawn_once_with_removed_before_added():
    body, changed = WHAT_CHANGED.diff_content(*EDITED_PARA)
    assert changed
    assert body == (
        '<p id="intro">The model is <del>fast</del>'
        "<ins>slow</ins> and cheap to run today.</p>"
    )
    assert _words_of(body, "old") == "The model is fast and cheap to run today.".split()
    assert _words_of(body, "new") == "The model is slow and cheap to run today.".split()
    assert _nests(body) and _ids_unique(body)


def test_a_rewritten_paragraph_is_still_one_copy_with_both_phrases_marked():
    body, changed = WHAT_CHANGED.diff_content(*REWRITTEN_PARA)
    assert changed
    assert body.count("<p") == 1 and "wc-" not in body
    assert _words_of(body, "old") == "Alpha beta gamma delta epsilon zeta.".split()
    assert _words_of(body, "new") == "Alpha eta gamma iota kappa zeta.".split()
    assert _nests(body)


def test_edited_table_row_is_one_row_inside_its_table():
    old = _rows(("alpha beta", "x"), ("Untouched cell", "y"))
    new = _rows(("alpha gamma", "x"), ("Untouched cell", "y"))
    body, changed = WHAT_CHANGED.diff_content(old, new)
    assert changed
    assert _row_tags(body) == [
        "<tr><td>alpha <del>beta</del><ins>gamma</ins></td><td>x</td></tr>",
        "<tr><td>Untouched cell</td><td>y</td></tr>",
    ]
    assert _nests(body)


def test_whole_added_and_removed_blocks_keep_their_light_shade():
    body, _ = WHAT_CHANGED.diff_content(
        "<p>Keep this one.</p><p>Gone entirely now.</p>",
        "<p>Keep this one.</p><h2>Fresh heading</h2>",
    )
    assert 'class="wc-block-removed"' in body and 'class="wc-block-added"' in body


def test_a_row_only_one_side_has_keeps_its_light_shade_in_its_cells():
    old = _rows(("alice", "10"))
    new = _rows(("alice", "10"), ("carol", "12"))
    body, _ = WHAT_CHANGED.diff_content(old, new)
    assert '<tr class="wc-block-added">' in body
    assert "tr.wc-block-added > :is(td, th)" in WHAT_CHANGED.DIFF_STYLE


def test_edits_are_marked_by_words_alone_no_option_remains():
    import inspect

    assert list(inspect.signature(WHAT_CHANGED.diff_content).parameters) == [
        "old",
        "new",
        "images",
    ]
    source = ENGINE_SCRIPT.read_text()
    assert "WC_EDIT_LAYOUT" not in source and "wc-edit-inline" not in source
    assert "wc-edit-blk" not in WHAT_CHANGED.DIFF_STYLE  # no tint on an edit


def test_source_views_keep_the_old_line_above_the_new_one():
    body = ENGINE.source_diff("alpha beta gamma\n", "alpha beta delta\n")
    assert body.index("wc-edit-old") < body.index("wc-edit-new")
    assert "<del>gamma</del>" in body and "<ins>delta</ins>" in body


def test_an_edited_block_is_a_change_the_fold_script_keeps_in_view():
    # Its words carry <ins>/<del>, which the fold script keeps; the source rows
    # and the shaded blocks are named in it as well.
    for marker in ("ins, del", ".wc-edit-old", ".wc-edit-new", ".wc-block-added"):
        assert marker in WHAT_CHANGED.FOLD_JS
    assert ".wc-edit-inline" not in WHAT_CHANGED.FOLD_JS


# The table of kinds (diff-engine.py's KINDS): each kind of content is one entry,
# and the aligner, the sanitizer, the units and the header all read it.


ROLES = {
    "paragraph": "text",
    "heading": "text",
    "list item": "text",
    "source line": "text",
    "list": "container",
    "table row": "row",
    "table": "container",
    "block": "container",
    "code block": "container",
    "authored edit mark": "container",
    "link": "inline",
    "inline text": "inline",
    "formatting": "inline",
    "evidence claim": "inline",
    "equation": "unit",
    "evidence popover": "unit",
    "figure": "unit",
    "inline svg": "unit",
    "diagram text": "unit",
}


def test_each_entry_of_the_table_has_the_role_the_aligner_gives_its_element():
    assert {kind.name: kind.role for kind in ENGINE.KINDS} == ROLES
    for kind in ENGINE.KINDS:
        for tag in kind.tags:
            assert ENGINE.role_of(tag, [kind.cls] if kind.cls else []) == kind.role, (
                kind.name,
                tag,
            )
    assert ENGINE.role_of("custom-element") == "container"
    # a class names a kind; the bare tag is the other kind
    assert ENGINE.role_of("span", ["math", "inline"]) == "unit"
    assert ENGINE.role_of("span", ["ev-pop"]) == "unit"
    assert ENGINE.role_of("span") == "inline"
    assert ENGINE.role_of("pre", ["mermaid", "mermaid-js"]) == "unit"
    assert ENGINE.role_of("pre", ["sourceCode"]) == "container"


def test_the_aligners_sets_are_read_from_the_table():
    assert ENGINE.TINT_BLOCKS == {"p", "h", "li", "dd", "dt", "wc-ln"}
    assert ENGINE.ROW_TAGS == {"tr"}
    assert {"em", "a", "span", "img", "br"} <= ENGINE.INLINE_TAGS
    assert not {"p", "div", "svg", "pre", "table"} & ENGINE.INLINE_TAGS


def test_every_unit_entry_says_what_is_a_change_and_how_it_is_drawn():
    units = [kind for kind in ENGINE.KINDS if kind.role == "unit"]
    assert {k.name for k in units} == {
        "equation",
        "evidence popover",
        "figure",
        "inline svg",
        "diagram text",
    }
    for kind in units:
        assert kind.unit.compare and kind.unit.draw, kind.name
    assert all(k.unit is None for k in ENGINE.KINDS if k.role != "unit")


def test_every_entry_of_the_table_is_named_in_the_header():
    header = ENGINE.__doc__
    for kind in ENGINE.KINDS:
        assert f"`{kind.name}`" in header, kind.name


def test_the_header_says_how_to_add_a_kind_and_why_this_engine():
    header = ENGINE.__doc__
    assert "Adding a kind" in header and "Why our own engine" in header
    for word in ("lxml.html.diff", "diff-match-patch", "dependency review"):
        assert word in header


def test_the_sanitizer_keeps_what_the_table_keeps_and_nothing_else():
    kept = {tag for kind in ENGINE.KINDS for tag in kind.keep}
    assert ENGINE.SAFE_TAGS == kept
    for kind in ENGINE.KINDS:
        for tag, attrs in kind.keep.items():
            assert set(attrs) <= ENGINE.TAG_SAFE_ATTRS[tag]
    # only tags the table names survive; the rest go, with their words
    out = ENGINE.sanitize_fragment("<p>a <blink>b</blink> <x-y>c</x-y></p>")
    assert out == "<p>a b c</p>"
    # an attribute the entry does not keep goes
    out = ENGINE.sanitize_fragment('<td colspan="2" style="x" data-a="1">c</td>')
    assert out == '<td colspan="2">c</td>'


def _wrapped(kind, tag, markup):
    """`markup` in the element its entry keeps it inside, if it does."""
    if tag in kind.inside:
        return f"<{kind.tags[0]}>{markup}</{kind.tags[0]}>"
    return markup


def test_the_sanitizer_keeps_each_attribute_the_table_names_and_drops_others():
    values = {"tabindex": "0", "style": "fill: red"}
    for kind in ENGINE.KINDS:
        for tag, attrs in {**kind.keep, **kind.inside}.items():
            for attr in attrs:
                value = values.get(attr, "a1")
                src = f'<{tag} {attr}="{value}" data-x="1" onclick="y">t</{tag}>'
                out = ENGINE.sanitize_fragment(_wrapped(kind, tag, src))
                assert f'{attr}="{value}"' in out, (kind.name, tag, attr, out)
                assert "data-x" not in out and "onclick" not in out, (tag, out)


def test_the_table_keeps_the_attributes_a_page_needs():
    needed = {
        "a": {"href"},
        "img": {"src", "alt", "width", "height"},
        "td": {"colspan", "rowspan"},
        "th": {"colspan", "rowspan", "scope"},
        "ol": {"start"},
        "span": {"tabindex"},
        "svg": {"viewbox", "width", "height"},
        "path": {"d", "fill", "stroke"},
        "text": {"x", "y", "text-anchor"},
    }
    kept = dict(ENGINE.TAG_SAFE_ATTRS)
    for inside in ENGINE.INSIDE_TAGS.values():
        for tag, attrs in inside.items():
            kept[tag] = kept.get(tag, set()) | attrs
    for tag, attrs in needed.items():
        assert attrs <= kept.get(tag, set()), tag
    assert "style" not in kept["p"]
    assert not {"onclick", "onload", "srcset", "id"} & set().union(*kept.values())


HOSTILE = (
    '<p onclick="alert(1)" style="x" id="a">Safe <strong>prose</strong>.</p>'
    '<a href="javascript:alert(1)">bad</a> <a href="java&#x73;cript:alert(2)">bad2</a>'
    '<img src="x" onerror="alert(3)"><script>alert(4)</script>'
    "<style>@import url(https://evil.example/x.css)</style>"
    '<iframe srcdoc="<script>alert(5)</script>">f</iframe>'
    '<svg onload="alert(6)"><script>alert(7)</script>'
    '<foreignObject><div onclick="alert(8)">x</div></foreignObject>'
    '<use href="https://evil.example/x.svg#a"/>'
    '<rect style="fill:url(https://evil.example/f)" fill="url(#a)" onmouseover="alert(9)"/>'
    '<a href="javascript:alert(10)"><text>t</text></a></svg>'
    '<video autoplay onerror="alert(11)" src="javascript:alert(12)">'
    '<source src="v.mp4" onerror="alert(13)"><track src="t.vtt"></video>'
    '<form action="/x"><input name="n"></form><math><mi>x</mi></math>'
    '<span class="math inline">\\(x\\)</span>'
)


def _assert_inert(fragment):
    low = fragment.lower()
    for bad in ("<script", "<style", "<iframe", "<foreignobject", "<use", "<form",
                "<input", "<track", "<math", "<link", "javascript:", "evil.example",
                "alert(", "url("):  # fmt: skip
        assert bad not in low, bad
    assert not re.search(r"\son[a-z]+\s*=", low)
    assert " style=" not in low


def test_diff_content_called_alone_comes_out_inert():
    body, changed = ENGINE.diff_content(HOSTILE, HOSTILE.replace("Safe", "Changed"))
    assert changed
    _assert_inert(body)
    assert "<strong>prose</strong>" in body
    # what is kept of the drawing is the safe subset; a video goes, as on main
    assert "<svg>" in body
    assert not re.search(r"<(video|source|track)|autoplay", body)


def test_diff_content_called_alone_is_inert_for_a_page_with_no_change_too():
    body, changed = ENGINE.diff_content(HOSTILE, HOSTILE)
    assert changed is False
    _assert_inert(body)


def test_source_diff_of_hostile_text_is_text():
    body = ENGINE.source_diff(HOSTILE + "\n", HOSTILE.replace("Safe", "X") + "\n")
    assert not re.search(r"<(script|style|iframe|svg|video|form|input)", body)
    assert "&lt;script&gt;" in body and "&lt;svg" in body


def test_an_inline_svg_keeps_only_a_safe_subset():
    out = ENGINE.sanitize_fragment(
        '<svg viewBox="0 0 10 10" onload="x()" xmlns="http://www.w3.org/2000/svg" '
        'style="; max-width: none; fill: url(https://evil.example/f)">'
        '<g class="node"><title>a</title>'
        '<polygon fill="white" stroke="black" points="0,0 1,1 2,0"/>'
        '<text style="fill: red; font-size: 12px; background: url(x)" x="1">a</text>'
        '</g><defs><linearGradient id="g"><stop offset="0"/></linearGradient></defs>'
        '<image href="https://evil.example/i.png"/>'
        '<animate attributeName="x"/></svg>'
    )
    assert out == (
        '<svg viewbox="0 0 10 10"><g class="node"><title>a</title>'
        '<polygon fill="white" stroke="black" points="0,0 1,1 2,0"></polygon>'
        '<text style="fill: red; font-size: 12px" x="1">a</text></g></svg>'
    )


GRAPH = (
    '<figure><div><svg width="62" height="116" viewBox="0 0 62 116">'
    '<g class="graph"><title>G</title>'
    '<ellipse fill="none" stroke="black" cx="27" cy="-90" rx="27" ry="18"/>'
    '<text text-anchor="middle" x="27" y="-85">{label}</text></g></svg></div>'
    "<figcaption>Figure 1.</figcaption></figure>"
)


def test_a_changed_inline_svg_is_drawn_old_and_new_never_marked_inside():
    old, new = GRAPH.format(label="a"), GRAPH.format(label="b")
    body, changed = ENGINE.diff_content(old, new)
    assert changed
    d, i = (
        body.index('<del class="wc-unit"><svg'),
        body.index('<ins class="wc-unit"><svg'),
    )
    assert d < i
    assert "<text" in body[d:i] and ">a</text>" in body[d:i]
    assert ">b</text>" in body[i:]
    # never marked inside: no ins/del between the drawing's own tags
    assert not re.search(r"<svg[^>]*>(?:(?!</svg>).)*<(?:ins|del)\b", body, re.S)
    assert "<figcaption>Figure 1.</figcaption>" in body


def test_an_unchanged_inline_svg_is_no_change_and_one_with_other_ids_neither():
    page = GRAPH.format(label="a")
    assert ENGINE.diff_content(page, page)[1] is False
    with_id = page.replace('<g class="graph">', '<g class="graph" id="graph0">')
    assert ENGINE.diff_content(page, with_id)[1] is False


def test_a_whole_added_or_removed_drawing_is_drawn_whole():
    old, new = "<p>Text.</p>", "<p>Text.</p>" + GRAPH.format(label="a")
    body, changed = ENGINE.diff_content(old, new)
    assert changed and "wc-block-added" in body and "<svg" in body
    body, changed = ENGINE.diff_content(new, old)
    assert changed and "wc-block-removed" in body and "<svg" in body


def test_a_changed_mermaid_diagram_is_its_text_old_and_new():
    page = '<div><pre class="mermaid mermaid-js">flowchart LR\n  A --&gt; {t}\n</pre></div>'
    body, changed = ENGINE.diff_content(page.format(t="B"), page.format(t="C"))
    assert changed
    d, i = (
        body.index('<del class="wc-unit"><pre class="mermaid'),
        body.index('<ins class="wc-unit"><pre class="mermaid'),
    )
    assert d < i
    assert "A --&gt; B" in body[d:i] and "A --&gt; C" in body[i:]
    # a code block that is not a diagram is still marked by its words
    code = "<pre><code>x = {v}</code></pre>"
    body, _ = ENGINE.diff_content(code.format(v=1), code.format(v=2))
    assert "wc-unit" not in body and "<del>1</del>" in body


def test_changed_figure_is_markup_for_old_and_new_side_by_side():
    page = '<p><img src="plot.png" alt="Plot"></p>'
    images = _images(
        {("old", "plot.png"): "aaaa", ("new", "plot.png"): "bbbb"},
        {"plot.png": "data:image/png;base64,OLD"},
    )
    body, _ = ENGINE.diff_content(page, page, images)
    # the old and the new are two siblings of one parent, the old first ...
    assert re.fullmatch(
        r'<p><del class="wc-unit"><img [^>]*></del><ins class="wc-unit"><img [^>]*></ins></p>',
        body,
    )
    css = ENGINE.DIFF_STYLE
    # ... which the stylesheet sets in a row, each half the width
    # (only when the parent holds nothing but the two, so a page is never a row)
    pair = (
        ":is(p, div, figure):has(> del.wc-unit > :is(img, svg, pre))"
        ":has(> ins.wc-unit > :is(img, svg, pre))"
        ":not(:has(> :not(:is(del, ins).wc-unit)))"
    )
    rule = re.search(re.escape(pair) + r" \{([^}]*)\}", css)
    assert "display: flex" in rule.group(1)
    assert re.search(re.escape(pair) + r" > \.wc-unit \{\s*flex: 1 1 0", css)
    # no red or green band behind an image, no outline, no fading
    assert not re.search(r"(ins|del) img[^{]*\{[^}]*(outline|opacity)", css)
    # a figure is a block, framed (see the framing tests below)
    assert re.search(
        r"\.wc-unit:is\([^{]*:has\(> :is\(img, svg, pre, div, figure\)\)\) \{\s*display: block;",
        css,
    )
    assert "outline: none" in css


def test_a_page_with_a_figure_pair_loads_the_pair_layout_script_once(tmp_path):
    page = '<p><img src="plot.png" alt="Plot"></p>'
    images = _images(
        {("old", "plot.png"): "aaaa", ("new", "plot.png"): "bbbb"},
        {"plot.png": "data:image/png;base64,OLD"},
    )
    body, _ = ENGINE.diff_content(page, page, images)
    script = ENGINE.pair_script(body)
    assert script.count("var STACK") == 1 and script.startswith("<script>")
    # it sets the stack by a class the stylesheet knows
    assert 'var STACK = "wc-pair-stack"' in script
    assert "wc-pair-stack" in ENGINE.DIFF_STYLE
    # a changed diagram is a figure pair too, a page without one has no script
    diagram = '<div><pre class="mermaid mermaid-js">flowchart LR\n  A --&gt; {t}\n</pre></div>'
    drawn, _ = ENGINE.diff_content(diagram.format(t="B"), diagram.format(t="C"))
    assert "var STACK" in ENGINE.pair_script(drawn)
    plain, _ = ENGINE.diff_content("<p>one two</p>", "<p>one three</p>")
    assert ENGINE.pair_script(plain) == ""
    # and the Mermaid script asks for it again once it has drawn
    assert "window.wcPairLayout" in ENGINE.mermaid_script(drawn)
    # on the page: before the Mermaid script, which calls it
    old, new = tmp_path / "old", tmp_path / "new"
    _mermaid_site(old, "B")
    _mermaid_site(new, "C")
    result = WHAT_CHANGED.build(old, new, "", "PR")
    assert result.count("var STACK") == 1
    assert result.index("var STACK") < result.index("window.mermaid;")


def test_a_stacked_pair_is_old_above_new_at_its_natural_size():
    css = ENGINE.DIFF_STYLE
    pair = (
        ":is(p, div, figure):has(> del.wc-unit > :is(img, svg, pre))"
        ":has(> ins.wc-unit > :is(img, svg, pre))"
        ":not(:has(> :not(:is(del, ins).wc-unit)))"
    )
    stack = re.search(re.escape(pair) + r"\.wc-pair-stack \{([^}]*)\}", css)
    assert "flex-direction: column" in stack.group(1)
    unit = re.search(re.escape(pair) + r"\.wc-pair-stack > \.wc-unit \{([^}]*)\}", css)
    assert "flex: none" in unit.group(1)
    # the rule is in the header's figure and diagram rows, in a sentence
    header = " ".join(ENGINE.__doc__.split())
    assert header.count("old above new at that size, up to the full column") == 2
    # the natural width is the page's own: an image's attribute or file, a
    # drawing's max-width, width or viewBox
    js = ENGINE.PAIR_JS
    for known in (
        "naturalWidth",
        "max-width",
        'getAttribute("viewBox")',
        'attrPx(el, "width")',
    ):
        assert known in js


def test_a_unit_that_is_not_framed_is_shaded_like_any_other_change():
    css = ENGINE.DIFF_STYLE
    assert ".wc-scope del.wc-unit { background: var(--wc-del-blk); }" in css
    assert ".wc-scope ins.wc-unit { background: var(--wc-ins-blk); }" in css
    assert not re.search(r"wc-unit[^{]*\{[^}]*outline:\s*(?!none)[^\s;}]", css)
    # an inline equation in edited text takes the word shade
    assert (
        'del.wc-unit:has(> mjx-container:not([display="true"])) { background: var(--wc-del-bg)'
        in css
    )


MATH_PAGE = '<p>Energy <span class="math inline">\\(E = mc^2\\)</span> holds.</p>'


def test_mathjax_is_loaded_only_for_a_page_with_math():
    assert ENGINE.math_script("<p>No equation.</p>") == ""
    assert ENGINE.math_script('<span class="mathematics">x</span>') == ""
    script = ENGINE.math_script("<p>x</p>", MATH_PAGE)
    assert script == ENGINE.math_script(MATH_PAGE)
    # MathJax 3.2.2, pinned, from jsDelivr, with its integrity hash
    assert (
        'src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-chtml-full.js"'
        in script
    )
    assert 'integrity="sha384-' in script and 'crossorigin="anonymous"' in script
    # the TeX delimiters the pages use, and the source view left out
    assert '["\\\\(", "\\\\)"]' in script and '["\\\\[", "\\\\]"]' in script
    assert '"ignoreHtmlClass": "wc-src"' in script
    assert script.count("<script") == 4


def test_the_source_view_is_never_typeset_and_never_calls_for_mathjax():
    source = ENGINE.source_diff(
        "Energy \\(E = mc^2\\) holds.\n", "Energy \\(E = m\\) holds.\n"
    )
    assert 'class="wc-src"' in source and ENGINE.math_script(source) == ""
    assert '"ignoreHtmlClass": "wc-src"' in ENGINE.math_script(MATH_PAGE)


def test_the_page_loads_mathjax_only_when_it_has_an_equation(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for root in (old, new):
        root.mkdir()
    (old / "a.html").write_text("<main><p>Old words.</p></main>")
    (new / "a.html").write_text("<main><p>New words.</p></main>")
    result = WHAT_CHANGED.build(old, new, "", "PR")
    assert "mathjax" not in result.lower()
    (old / "a.html").write_text("<main>" + MATH_PAGE + "</main>")
    (new / "a.html").write_text("<main>" + MATH_PAGE.replace("mc^2", "m") + "</main>")
    result = WHAT_CHANGED.build(old, new, "", "PR")
    assert result.count("mathjax@3.2.2/es5/tex-chtml-full.js") == 1
    assert 'class="wc-unit"' in result


def test_the_outputs_are_one_table_with_a_comparer_each():
    names = list(WHAT_CHANGED.OUTPUT_KINDS)
    assert set(names) == {
        "site page",
        "page made by script",
        "slide deck",
        "LaTeX paper",
        "data file",
    }
    for output in WHAT_CHANGED.OUTPUT_KINDS.values():
        assert callable(output.compare) and output.recognised, output.name
        assert f"`{output.name}`" in ENGINE.__doc__ or output.name in ENGINE.__doc__
    engine = WHAT_CHANGED._engine  # (the one what-changed.py loaded)
    assert WHAT_CHANGED.OUTPUT_KINDS["data file"].compare is engine.source_diff
    assert WHAT_CHANGED.OUTPUT_KINDS["site page"].compare is WHAT_CHANGED.site_page


def test_a_page_goes_to_the_comparer_of_its_output_kind():
    prose = "<p>Words.</p>"
    widget = '<div class="plotly-graph-div">x</div>'
    pick = WHAT_CHANGED.page_output
    assert pick(prose, prose).name == "site page"
    assert pick(None, prose).name == "site page"
    assert pick(prose, widget).name == "page made by script"
    assert pick(widget, None).name == "page made by script"


# --- Findings of the independent review of the new engine (apwde-4u2) ---


VOID_THEN_TEXT = "<p>a</p><input name=n><embed src=x><track src=t><p>{}</p>"


def test_a_dropped_void_element_does_not_swallow_the_page():
    # A void element has no end tag, so dropping one must not drop what follows.
    old, new = (
        VOID_THEN_TEXT.format("Old results"),
        VOID_THEN_TEXT.format("New results"),
    )
    body, changed = ENGINE.diff_content(old, new)
    assert changed and "Old" in body and "New" in body
    assert "<input" not in body and "<embed" not in body and "<track" not in body
    for void in ("<input name=n>", "<link rel=x>", "<meta name=n>", "<embed src=x>"):
        out = ENGINE.sanitize_fragment(f"<p>a</p>{void}<p>b</p>")
        assert out == "<p>a</p><p>b</p>", (void, out)
    # inside a drawing too, and a void element inside a dropped element
    out = ENGINE.sanitize_fragment('<svg><track src="x"><text>t</text></svg><p>b</p>')
    assert out == "<svg><text>t</text></svg><p>b</p>"
    out = ENGINE.sanitize_fragment("<form><input name=n></form><p>b</p>")
    assert out == "<p>b</p>"
    # a video, with its sources and tracks, goes whole, and the page after it stays
    video = '<video controls><source src="c.mp4"><track src="c.vtt"></video>'
    assert ENGINE.sanitize_fragment(f"<p>a</p>{video}<p>b</p>") == "<p>a</p><p>b</p>"


def test_a_page_with_a_void_element_keeps_its_text_in_a_build(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for root, word in ((old, "Old"), (new, "New")):
        root.mkdir()
        (root / "index.html").write_text(
            f"<main>{VOID_THEN_TEXT.format(word + ' results')}</main>"
        )
    result = WHAT_CHANGED.build(old, new, "", "PR")
    assert "<del>Old</del>" in result and "<ins>New</ins>" in result
    assert "<track" not in result


def test_a_drawing_keeps_no_reference_outside_itself():
    hostile = (
        r'<svg><rect fill="u\72l(https://example.invalid/a.svg#p)"/></svg>',
        '<svg><rect stroke="url(https://example.invalid/a.svg#p)"/></svg>',
        '<svg><rect fill="&#117;rl(https://example.invalid/a.svg#p)"/></svg>',
        r'<svg><rect style="fill: u\72l(https://example.invalid/a.svg#p)"/></svg>',
        '<svg><a href="https://example.invalid/"><text>t</text></a></svg>',
        '<svg><a xlink:href="https://example.invalid/"><text>t</text></a></svg>',
    )
    for markup in hostile:
        assert "example.invalid" not in ENGINE.sanitize_fragment(markup), markup
        body, _ = ENGINE.diff_content(markup, markup.replace("rect", "path"))
        assert "example.invalid" not in body, markup
    # the labels of a linked node stay, and plain paint stays
    out = ENGINE.sanitize_fragment(
        '<svg><a href="https://example.invalid/"><text fill="red">t</text></a></svg>'
    )
    assert "<text" in out and ">t</text>" in out and 'fill="red"' in out


HREF_PAYLOAD = (
    '<p><span class="math inline">\\( \\href{javascript:alert(1)}{x} \\)</span></p>'
)


def _mathjax_config(script):
    text = re.search(
        r"window\.MathJax = (\{.*?\});window\.MathJax\.startup\.ready", script, re.S
    ).group(1)
    return json.loads(text)


def test_mathjax_is_typeset_with_its_safe_component_so_a_link_in_tex_cannot_run():
    # The sanitizer leaves TeX alone (it is text), so an \href to a javascript: URL
    # reaches MathJax, which would draw it as a live link. The page typesets
    # only with MathJax's own safe component, executable schemes switched off.
    body, _ = ENGINE.diff_content("", HREF_PAYLOAD)
    assert (
        "javascript:alert(1)" in body
    )  # the payload is there; the script is the guard
    script = ENGINE.math_script(body)
    # the main script and the safe component, each pinned by version and hash
    tags = re.findall(
        r"<script src=\"([^\"]+)\" integrity=\"(sha384-[^\"]{64})\"", script
    )
    assert [url for url, _ in tags] == [
        "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-chtml-full.js",
        "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/ui/safe.js",
    ]
    assert tags[1][1] == ENGINE.MATHJAX_SAFE_SRI
    assert script.count('crossorigin="anonymous"') == 2
    cfg = _mathjax_config(script)
    safe = cfg["options"]["safeOptions"]
    assert safe["safeProtocols"]["javascript"] is False
    assert safe["safeProtocols"]["data"] is False
    assert safe["allow"] == {
        "URLs": "safe",
        "classes": "safe",
        "cssIDs": "safe",
        "styles": "safe",
    }
    # it typesets only once the safe component is there, never without it
    assert cfg["startup"]["typeset"] is False
    assert "typesetPromise" in script and "_.ui.safe" in script
    assert script.index("typesetPromise") > script.index("ui/safe.js")


def test_mathjax_builds_its_document_only_after_the_safe_component_has_run():
    # The main bundle builds MathJax's handler and document as soon as it has
    # loaded, before the next <script>; a safe.js loaded after that reaches no
    # document. So `ready` is held before the main script, and defaultReady()
    # (which builds the document) is called only after safe.js, and only if it ran.
    script = ENGINE.math_script(HREF_PAYLOAD)
    held = script.index("window.MathJax.startup.ready = function () {};")
    main = script.index("tex-chtml-full.js")
    safe = script.index("ui/safe.js")
    build = script.index("defaultReady()")
    typeset = script.index("typesetPromise")
    assert held < main < safe < build < typeset
    assert script.count("defaultReady") == 2  # the guard and the call
    guard = script.index("defaultReady && ")
    assert build > guard and script.index("_.ui.safe") < build
    # the loader does not load it unpinned, and nothing builds it earlier
    assert "ui/safe" not in json.dumps(_mathjax_config(script).get("loader", {}))
    assert script.count("defaultReady()") == 1


def test_a_build_with_a_link_in_tex_typesets_it_with_the_safe_component(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for root, word in ((old, "x"), (new, "y")):
        root.mkdir()
        (root / "index.html").write_text(
            "<main>" + HREF_PAYLOAD.replace("{x}", "{" + word + "}") + "</main>"
        )
    result = WHAT_CHANGED.build(old, new, "", "PR")
    assert "mathjax@3.2.2/es5/ui/safe.js" in result
    assert result.index("ui/safe.js") > result.index("tex-chtml-full.js")
    assert '"javascript": false' in result


def test_an_image_whose_src_changed_is_drawn_before_and_after():
    images = _images(
        {("old", "before.png"): "aaaa", ("new", "after.png"): "bbbb"},
        {"before.png": "data:image/png;base64,OLD"},
    )
    body, changed = ENGINE.diff_content(
        '<p><img src="before.png" alt="plot"></p>',
        '<p><img src="after.png" alt="plot"></p>',
        images,
    )
    assert changed
    assert body == (
        '<p><del class="wc-unit"><img src="data:image/png;base64,OLD" alt="plot"></del>'
        '<ins class="wc-unit"><img src="after.png" alt="plot"></ins></p>'
    )
    # a size or an alt edited with the file: the same two figures
    body, _ = ENGINE.diff_content(
        '<p><img src="before.png" alt="plot" width="300"></p>',
        '<p><img src="after.png" alt="a plot" width="500"></p>',
        images,
    )
    assert body.count("<img") == 2 and "wc-link-changed" not in body
    # with no way to read the files the figure is still drawn old and new, with
    # no outline on the new one
    body, changed = ENGINE.diff_content(
        '<p><img src="before.png"></p>', '<p><img src="after.png"></p>'
    )
    assert changed and body.count("<img") == 2
    assert "wc-link-changed" not in body and "data-wc-was" not in body
    # a link whose target changed is still marked, not drawn twice
    body, _ = ENGINE.diff_content(
        '<p><a href="a">x</a></p>', '<p><a href="b">x</a></p>'
    )
    assert "wc-link-changed" in body


def test_a_page_whose_image_has_a_new_src_shows_the_old_file_beside_the_new(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for root, name, data in (
        (old, "before.png", b"OLDPNG"),
        (new, "after.png", b"NEW"),
    ):
        root.mkdir()
        (root / name).write_bytes(data)
        (root / "index.html").write_text(
            f'<main><p><img src="{name}" alt="Plot"></p><p>Figure 1.</p></main>'
        )
    result = WHAT_CHANGED.build(old, new, "", "PR")
    assert re.search(
        r'<del class="wc-unit"><img src="data:image/png;base64,T0xEUE5H" alt="Plot">'
        r'</del><ins class="wc-unit"><img src="after.png" alt="Plot"></ins>',
        result,
    )
    assert not re.search(r"<img[^>]*wc-link-changed", result)


QUARTO_CELL = (
    '<div class="{classes}"><div><figure class="figure"><div>'
    "<svg><g><text>A</text></g></svg></div></figure></div></div>"
)


def test_a_drawing_only_cell_with_other_classes_is_still_a_drawing():
    for classes in (
        "cell-output-display column-page",
        "column-page cell-output-display",
        "cell-output-display\tcolumn-body",
    ):
        cell = QUARTO_CELL.format(classes=classes)
        assert not WHAT_CHANGED.has_computed_output(cell), classes
    # the recognizer is the table's: a Mermaid cell is a drawing too
    mermaid = '<div class="cell-output-display column-page"><pre class="mermaid">A</pre></div>'
    assert not WHAT_CHANGED.has_computed_output(mermaid)
    # other output still is computed
    plot = '<div class="cell-output-display column-page"><img src="p.png"></div>'
    assert WHAT_CHANGED.has_computed_output(plot)
    both = QUARTO_CELL.format(classes="cell-output-display column-page").replace(
        "</svg>", "</svg><table></table>"
    )
    assert WHAT_CHANGED.has_computed_output(both)


def test_a_page_with_a_classed_drawing_cell_is_compared_not_linked(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for root, label in ((old, "a"), (new, "b")):
        root.mkdir()
        cell = QUARTO_CELL.format(classes="cell-output-display column-page")
        (root / "p.html").write_text(
            f"<main><p>Same words.</p>{cell.replace('>A<', f'>{label}<')}</main>"
        )
    result = WHAT_CHANGED.build(old, new, "", "PR")
    assert "renders its content with client-side scripts" not in result
    assert re.search(r'</svg></del><ins class="wc-unit"><svg', result)


def test_a_kind_added_by_its_entry_alone_is_extracted_owned_and_restored(monkeypatch):
    class NewUnit(ENGINE.Unit):
        order = 5

        @classmethod
        def owns(cls, kind, text):
            return kind == "word" and text == "custom-unit"

        @classmethod
        def extract(cls, content, side, images):
            return content.replace("CUSTOM", "custom-unit"), {"k": "CUSTOM"}

        @classmethod
        def restore(cls, content, store, images):
            return content.replace("custom-unit", "[" + store["k"] + "]")

    entry = ENGINE.Kind(
        "new kind", ("custom-kind",), None, "unit", {}, NewUnit("whole", "whole")
    )
    monkeypatch.setattr(ENGINE, "KINDS", ENGINE.KINDS + (entry,))
    assert ENGINE.unit_of("word", "custom-unit") is NewUnit
    assert ENGINE.unit_of("word", "plain") is None
    assert NewUnit in ENGINE.passes() and ENGINE.passes()[-1] is NewUnit
    body, changed = ENGINE.diff_content("<p>x</p>", "<p>x CUSTOM</p>")
    assert changed and '<ins class="wc-unit">[CUSTOM]</ins>' in body
    # the order of the passes is each unit's own, not the order of the entries
    assert [u.order for u in ENGINE.passes()] == [0, 1, 2, 5]


def test_an_image_kind_owns_the_tags_its_entry_names(monkeypatch):
    entry = ENGINE.Kind(
        "picture", ("pic",), None, "unit", {"pic": ("src",)},
        ENGINE.ImageUnit("whole", "whole", figure=True),
    )  # fmt: skip
    assert not ENGINE.unit_of("tag", "<pic src='a'>")
    monkeypatch.setattr(ENGINE, "KINDS", ENGINE.KINDS + (entry,))
    assert ENGINE.unit_of("tag", "<pic src='a'>") is ENGINE.ImageUnit
    assert ENGINE.unit_of("tag", "<img src='a'>") is ENGINE.ImageUnit
    assert not ENGINE.unit_of("tag", "<em>")


def test_the_recognizers_are_read_from_the_entries_of_the_table():
    kinds = ENGINE.KINDS
    # formatting and the evidence claim are entries, not lists beside the table
    assert ENGINE.FORMAT_TAGS == {t for k in kinds if k.format for t in k.tags}
    assert {"b", "em", "strong", "code", "sup"} <= ENGINE.FORMAT_TAGS
    assert "span" not in ENGINE.FORMAT_TAGS
    assert [k.name for k in kinds if k.structural] == ["evidence claim"]
    assert ENGINE.is_structural('<span class="ev">')
    assert ENGINE.is_structural("<span data-x='1' class='a ev b'>")
    assert not ENGINE.is_structural('<span class="evidence">')
    assert not ENGINE.is_structural("</span>") and not ENGINE.is_structural("<em>")
    # the figure-like tags (the stylesheet's, the pair's) are those of the figure entries
    figures = [t for k in kinds if k.unit is not None and k.unit.figure for t in k.tags]
    assert figures == ["img", "svg", "pre"]
    assert ENGINE.FIGURE_TAGS == tuple(figures)
    assert ":is(img, svg, pre)" in ENGINE.DIFF_STYLE
    assert ENGINE.FILE_TAGS == ["img"]
    assert ENGINE.names_files('<p><img src="a.png"></p>') and not ENGINE.names_files(
        "<p>a</p>"
    )
    # what a drawing-only cell holds is recognised by the same entries
    assert ENGINE.holds_drawing("<div><svg><text>a</text></svg></div>")
    assert ENGINE.holds_drawing('<pre class="mermaid">a</pre>')
    assert not ENGINE.holds_drawing("<pre><code>a</code></pre><p>x</p>")
    assert not ENGINE.holds_drawing('<span class="math">\\(x\\)</span>')


# --- Mermaid, drawn with the site's own copy -------------------------------------

MERMAID_SRC = "site_libs/quarto-diagram/mermaid.min.js"
HOSTILE_MERMAID = (
    "%%{init: {'securityLevel': 'loose', 'themeCSS': 'a{background:url(//x/y)}'}}%%\n"
    "flowchart LR\n"
    '  A["<img src=x onerror=alert(1)>"] --> B["<script>alert(2)</script>"]\n'
    '  click A "javascript:alert(3)"\n'
    '  click B href "javascript:alert(4)" _blank\n'
    '  C["<a href=\\"javascript:alert(5)\\">go</a>"]\n'
)


def _mermaid_site(root, label, mermaid=True, extra="", name="p.html", libs=True):
    """A rendered site as Quarto writes it: one page with a Mermaid cell."""
    root.mkdir(parents=True, exist_ok=True)
    page = root / name
    page.parent.mkdir(parents=True, exist_ok=True)
    depth = len(Path(name).parts) - 1
    script = f'<script src="{"../" * depth}{MERMAID_SRC}"></script>' if mermaid else ""
    page.write_text(
        f"<html><head>{script}</head><body><main><p>Same words.</p>"
        '<div class="cell"><div class="cell-output-display"><div><figure class="figure">'
        f'<div><pre class="mermaid mermaid-js">flowchart LR\n  A --&gt; {label}\n</pre>'
        f"</div></figure></div></div></div>{extra}</main></body></html>"
    )
    if mermaid and libs:
        lib = root / MERMAID_SRC
        lib.parent.mkdir(parents=True, exist_ok=True)
        lib.write_text("globalThis.mermaid = {};")


def _script_srcs(result):
    """Every external script a page loads, as (src, integrity)."""
    return [
        (m.group(1), (re.search(r'integrity="([^"]*)"', m.group(0)) or [None, None])[1])
        for m in re.finditer(r'<script\b[^>]*\ssrc="([^"]*)"[^>]*>', result)
    ]


def _mermaid_scripts(result):
    return [t for t in _script_srcs(result) if "mermaid" in t[0]]


PINNED_MERMAID = (ENGINE.MERMAID_URL, ENGINE.MERMAID_SRI)


def _mermaid_config(script):
    text = re.search(r"var config = (\{.*?\});\n", script, re.S).group(1)
    return json.loads(text)


def test_the_page_loads_pinned_mermaid_only_when_it_has_a_mermaid_unit(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _mermaid_site(old, "B")
    _mermaid_site(new, "C")
    result = WHAT_CHANGED.build(old, new, "", "PR")
    # one release from jsDelivr with its integrity hash, once, then the drawing
    # script; never the site's own file
    assert _mermaid_scripts(result) == [PINNED_MERMAID]
    assert PINNED_MERMAID[0].startswith("https://cdn.jsdelivr.net/npm/mermaid@11.12.0/")
    assert PINNED_MERMAID[1].startswith("sha384-")
    assert 'crossorigin="anonymous"' in result.split(PINNED_MERMAID[0])[1][:200]
    assert result.count("var mermaid = window.mermaid;") == 1
    assert result.index(PINNED_MERMAID[0]) < result.index("window.mermaid;")
    assert MERMAID_SRC not in result
    # a diagram nobody changed, a changed page with no diagram: no Mermaid
    same_old, same_new = tmp_path / "so", tmp_path / "sn"
    _mermaid_site(same_old, "B", extra="<p>Old.</p>")
    _mermaid_site(same_new, "B", extra="<p>New.</p>")
    unchanged = WHAT_CHANGED.build(same_old, same_new, "", "PR")
    assert "New." in unchanged
    assert _mermaid_scripts(unchanged) == [] and "window.mermaid" not in unchanged
    plain_old, plain_new = tmp_path / "po", tmp_path / "pn"
    for root, word in ((plain_old, "a"), (plain_new, "b")):
        root.mkdir()
        (root / "q.html").write_text(f"<main><p>Word {word}.</p></main>")
    plain = WHAT_CHANGED.build(plain_old, plain_new, "", "PR")
    assert _mermaid_scripts(plain) == [] and "window.mermaid" not in plain
    # and the engine's own call says the same
    drawn, _ = ENGINE.diff_content(
        '<div><pre class="mermaid">flowchart LR\n A --&gt; B</pre></div>',
        '<div><pre class="mermaid">flowchart LR\n A --&gt; C</pre></div>',
    )
    assert _mermaid_scripts(ENGINE.mermaid_script(drawn)) == [PINNED_MERMAID]
    assert ENGINE.mermaid_script("<p>no diagram</p>") == ""


def test_mermaid_is_initialised_strict_with_no_auto_start():
    page = '<div><pre class="mermaid mermaid-js">flowchart LR\n  A --&gt; {t}\n</pre></div>'
    body, _ = ENGINE.diff_content(page.format(t="B"), page.format(t="C"))
    script = ENGINE.mermaid_script(body)
    config = _mermaid_config(script)
    assert config["securityLevel"] == "strict"
    assert config["startOnLoad"] is False
    # a directive in the diagram cannot lower the level, load on start, or add CSS
    assert {"securityLevel", "startOnLoad", "themeCSS", "secure"} <= set(
        config["secure"]
    )
    assert config["suppressErrorRendering"] is True
    # initialised before anything is drawn, and nothing but the pairs is drawn
    assert script.index("mermaid.initialize(config)") < script.index("mermaid.render(")
    assert '".wc-unit > pre.mermaid"' in script
    assert "mermaid.run" not in script and "contentLoaded" not in script
    assert ENGINE.MERMAID_CONFIG["securityLevel"] == "strict"
    assert "loose" not in script.replace("lower", "")


def test_a_diagram_keeps_its_text_wrapped_until_mermaid_draws_it(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _mermaid_site(old, "B", mermaid=False)
    _mermaid_site(new, "C", mermaid=False)
    result = WHAT_CHANGED.build(old, new, "", "PR")
    # the text is there, old and new, as before, whether or not Mermaid loads
    assert "A --&gt; B" in result and "A --&gt; C" in result
    assert result.count('<pre class="mermaid mermaid-js">') == 2
    # and it wraps where it was cut off at the right
    css = ENGINE.DIFF_STYLE
    assert (
        ".wc-scope pre.mermaid { white-space: pre-wrap; overflow-wrap: anywhere; }"
        in css
    )
    # the drawing script leaves the text when Mermaid is not there (no network, a
    # hash that does not match) or fails
    js = ENGINE.MERMAID_JS
    assert "if (!mermaid ||" in js and ".catch(function () {})" in js


def _hostile_site(root, label, page_script):
    """The review's fixture: a Mermaid diagram changed from B to C, a page head
    that names `page_script`, and files that would set a global if run."""
    (root / "uploads").mkdir(parents=True)
    (root / "site_libs/quarto-diagram").mkdir(parents=True)
    (root / "index.html").write_text(
        f"<html><head>{page_script}</head><body><main>"
        f'<div><pre class="mermaid">flowchart LR\n A --&gt; {label}</pre></div>'
        "</main></body></html>"
    )
    for lib in ("uploads/mermaid.js", MERMAID_SRC):
        (root / lib).write_text("globalThis.unreviewedCodeRan = true;")


def test_a_script_in_a_comment_or_named_by_a_page_is_never_emitted(tmp_path):
    # a commented script tag, a live one, a CDN one, the site's own library
    heads = [
        '<!-- <script src="uploads/mermaid.js"></script> -->',
        '<script src="uploads/mermaid.js"></script>',
        '<script src="https://evil.example/mermaid.min.js"></script>',
        f'<script src="{MERMAID_SRC}"></script>',
    ]
    for n, head in enumerate(heads):
        old, new = tmp_path / f"b{n}" / "old", tmp_path / f"b{n}" / "new"
        _hostile_site(old, "B", head)
        _hostile_site(new, "C", head)
        result = WHAT_CHANGED.build(old, new, "", "PR")
        assert "A --&gt; C" in result, head
        # the diagram is changed, so Mermaid is loaded; only the pinned one
        assert _mermaid_scripts(result) == [PINNED_MERMAID], head
        # no script a site ships or names reaches the report
        for src, _ in _script_srcs(result):
            assert src.startswith("https://cdn.jsdelivr.net/npm/"), (head, src)
        assert "uploads/mermaid.js" not in result and "evil.example" not in result
        assert "unreviewedCodeRan" not in result


def test_a_site_with_its_own_mermaid_file_never_has_it_loaded(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _mermaid_site(old, "B")
    _mermaid_site(new, "C")
    result = WHAT_CHANGED.build(old, new, "", "PR", theme_url_prefix="assets/")
    assert [s for s, _ in _script_srcs(result)] == [PINNED_MERMAID[0]]
    assert MERMAID_SRC not in result
    # the engine has no way left to take a script from a page
    assert not hasattr(ENGINE, "site_mermaid_src")
    assert not hasattr(WHAT_CHANGED, "site_mermaid_src")
    assert not hasattr(WHAT_CHANGED, "mermaid_url")


def test_hostile_mermaid_labels_are_inert_by_config_and_by_scrub():
    page = '<div><pre class="mermaid mermaid-js">{t}</pre></div>'
    text = html.escape(HOSTILE_MERMAID, quote=False)
    body, changed = ENGINE.diff_content(
        page.format(t="flowchart LR\n A --&gt; B"), page.format(t=text)
    )
    assert changed
    unit = body[body.index('<ins class="wc-unit"><pre class="mermaid') :]
    # the labels reach the page only as the diagram's text: escaped, never as markup
    assert "&lt;img src=x onerror=alert(1)&gt;" in unit
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in unit
    assert (
        "<img" not in body
        and "<script" not in body
        and "onerror=alert" not in re.sub(r"&lt;img[^&]*", "", body)
    )
    assert "javascript:alert(3)" in unit  # text of the click line, drawn by Mermaid
    # what makes them inert when drawn: strict mode with the directive unable to
    # lower it, and a scrub of the SVG that takes out script, handlers and links
    script = ENGINE.mermaid_script(body)
    config = _mermaid_config(script)
    assert config["securityLevel"] == "strict"
    assert {"securityLevel", "themeCSS"} <= set(config["secure"])
    assert "scrub(doc.body)" in script
    assert 'n.indexOf("on") === 0' in script and 'charAt(0) !== "#"' in script
    assert "script|iframe|object|embed" in script
    # the diagram is read as text, never inserted as markup
    assert "textContent" in script and "innerHTML" not in script


def _rule(css, selector, exact=True):
    """The declarations of the first rule whose selector is `selector` (or, not
    exact, contains it)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        found = " ".join(match.group(1).split())
        if found == selector if exact else selector in found:
            return match.group(2)
    raise AssertionError(f"no rule for {selector}")


FRAMED_UNITS = (
    '.wc-scope :is(del, ins).wc-unit:is(:has(mjx-container[display="true"]), '
    ":has(> :is(img, svg, pre, div, figure)))"
)


def test_a_whole_unit_is_framed_old_in_red_new_in_green_with_a_label_never_filled():
    css = ENGINE.DIFF_STYLE
    # a display equation, a figure, a drawing or a diagram is framed ...
    frame = _rule(css, FRAMED_UNITS)
    assert "border: 1px solid var(--wc-frame)" in frame
    assert "background: transparent" in frame  # ... on the page's own background
    assert "display: block" in frame
    # the old in the red of its side, the new in the green, each labelled
    assert (
        'del.wc-unit { --wc-frame: var(--wc-del-line); --wc-label: "Before"; }' in css
    )
    assert 'ins.wc-unit { --wc-frame: var(--wc-ins-line); --wc-label: "After"; }' in css
    label = _rule(css, FRAMED_UNITS + "::before")
    assert "content: var(--wc-label)" in label
    assert "color: var(--wc-frame)" in label  # in the colour of its frame
    # a block that holds only such a unit has no shade either
    only = _rule(css, ".wc-block-added):not(tr):is(", exact=False)
    assert "background: transparent" in only
    selector = re.search(r"\.wc-block-added\):not\(tr\):is\(([^{]*)\) \{", css).group(1)
    assert "mjx-container[display=" in selector and "img, svg, pre" in selector
    assert ":has(> :is(del, ins).wc-unit:only-child" in selector
    assert ".wc-block-removed" in css and ".wc-block-added" in css
    # an inline equation stays marked like words
    inline = 'ins.wc-unit:has(> mjx-container:not([display="true"])) { background: var(--wc-ins-bg); }'
    assert inline in css


def test_the_frames_follow_the_dark_palette():
    # the frame colours are the palette's own lines, which dark mode redefines
    for name in ("--wc-del-line", "--wc-ins-line"):
        assert re.search(
            rf"\[data-wc-mode=\"dark\"\] \.wc-scope \{{[^}}]*{name}:", ENGINE.DIFF_STYLE
        )


def test_a_figure_pair_is_still_old_and_new_side_by_side_when_framed():
    page = '<p><img src="plot.png" alt="Plot"></p>'
    images = _images(
        {("old", "plot.png"): "aaaa", ("new", "plot.png"): "bbbb"},
        {"plot.png": "data:image/png;base64,OLD"},
    )
    body, _ = ENGINE.diff_content(page, page, images)
    assert '<del class="wc-unit"><img ' in body and '<ins class="wc-unit"><img ' in body
    # the layout rules stand on the units, not on their fill
    assert "flex: 1 1 0" in ENGINE.DIFF_STYLE and "wc-pair-stack" in ENGINE.DIFF_STYLE


def test_every_fold_strip_has_one_look_tinted_what_changeds_blue():
    css = ENGINE.DIFF_STYLE
    # the page's strips and the deck's "unchanged slides" are one rule
    rule = re.search(
        r"\.wc-scope :is\(div, li\)\.wc-strip, \.wc-scope \.wc-strip-bar, "
        r"\.wc-scope \.wc-expander > summary \{([^}]*)\}",
        css,
    )
    assert rule, "the page's strip and the deck's strip share a rule"
    assert "background: var(--wc-strip)" in rule.group(1)
    assert "color: inherit" in rule.group(1)
    # the tint is What changed's blue, never red or green; the arrows are blue
    assert "--wc-strip: color-mix(in srgb, var(--wc-changed) 16%, transparent)" in css
    assert (
        "--wc-strip-line: color-mix(in srgb, var(--wc-changed) 45%, transparent)" in css
    )
    arrows = _rule(
        css, ".wc-scope .wc-strip button:not(.wc-more), .wc-scope .wc-expander-icon"
    )
    assert "color: var(--wc-changed)" in arrows
    assert ".wc-expander-icon" in css
    # no second copy of the look in the deck's own style
    deck = _deck_module()
    assert "rgba(84,174,255" not in deck.LIVE_STYLE
    assert "summary" not in deck.LIVE_STYLE


def _deck_module():
    spec = importlib.util.spec_from_file_location(
        "deck_review_here", SCRIPT.with_name("deck-review.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_strips_names_come_from_the_table_of_kinds_in_a_readers_terms():
    names = ENGINE._STRIP_TAG_NAMES
    assert names["p"] == "paragraph" and names["li"] == "list item"
    assert names["tr"] == "table row" and names["pre"] == "code block"
    assert names["section"] == "section" and names["figure"] == "figure"
    assert "callout" in ENGINE._STRIP_CLASS_NAMES
    # the page's script carries them, so a fold can say them
    assert '"p":"paragraph"' in ENGINE.FOLD_JS and '"li":"list item"' in ENGINE.FOLD_JS
    assert "__TAG_NAMES__" not in ENGINE.FOLD_JS


def test_the_evidence_chip_takes_the_dark_on_bright_text_of_the_other_tags():
    css = ENGINE.DIFF_STYLE
    chip = _rule(css, ".wc-scope .wc-ev-chip")
    assert "color: var(--wc-tag-fg)" in chip
    # the same variable the tags use, which is dark on the bright fills in dark mode
    assert "color: var(--wc-tag-fg)" in _rule(css, ".wc-scope .tag")
    assert "--wc-tag-fg: #0d1117" in css


def test_what_changed_reads_wider_than_prose():
    css = ENGINE.DIFF_STYLE
    assert "max-width: 1040px" in _rule(css, ".wc-scope main.content")
    assert "margin-inline: auto" in _rule(css, ".wc-scope main.content")
    # Quarto's grid is set aside, so that the column's width is the one above
    assert "display: block" in _rule(css, ".wc-scope.page-columns")


def test_a_wholly_added_block_with_a_hanging_first_line_is_shaded_from_the_line():
    js = ENGINE.FOLD_JS
    assert "function shadeHanging" in js and "s.textIndent" in js
    assert ".wc-block-added, .wc-block-removed" in js
    assert "shadeHanging(document)" in js


def test_a_paper_note_says_nothing_when_its_marked_pdf_says_it_all(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (new / "paper-previews/paper").mkdir(parents=True)
    (new / "paper-previews/paper/preview.json").write_text(
        json.dumps({"changed": True, "diff": True})
    )
    result = WHAT_CHANGED.build(old, new, "", "PR preview")
    assert "LaTeX edits are highlighted in the diff PDF" not in result
    # the section goes from its heading to the viewer
    assert re.search(r'</h2><div class="paper-view">', result)
    # a note that says something else stays
    (new / "paper-previews/paper/preview.json").write_text(
        json.dumps({"changed": True, "diff": True, "other_inputs": True})
    )
    other = WHAT_CHANGED.build(old, new, "", "PR preview")
    assert "other paper inputs may not be" in other


def test_the_papers_bar_is_title_file_then_the_switch_then_the_whole_window_button(
    tmp_path,
):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (new / "paper-previews/paper").mkdir(parents=True)
    (new / "paper-previews/paper/preview.json").write_text(
        json.dumps({"changed": True, "diff": True})
    )
    result = WHAT_CHANGED.build(old, new, "", "PR preview")
    bar = re.search(r'<div class="paper-bar">(.*?)</div><object', result, re.S).group(1)
    order = re.findall(r'class="(paper-[a-z]+)"', bar)
    assert order == ["paper-title", "paper-file", "paper-modes", "paper-expand"]
    assert '<code class="paper-file">paper/main.tex</code>' in bar
    assert ">Changes marked</button>" in bar and "This PR" not in result
    assert ">Clean</button>" in bar
    # the file is the manifest's when it names one
    (new / "paper-previews/paper/preview.json").write_text(
        json.dumps({"changed": True, "diff": True, "main": "article.tex"})
    )
    named = WHAT_CHANGED.build(old, new, "", "PR preview")
    assert '<code class="paper-file">paper/article.tex</code>' in named
    # the switch is at the far right with the button after it
    css = ENGINE.DIFF_STYLE
    assert "margin-left: auto" in _rule(css, ".wc-scope .paper-modes")
    assert "margin-left: 0" in _rule(css, ".wc-scope .paper-modes ~ .paper-expand")


def test_the_paper_leaves_whole_window_on_escape_keeping_focus_and_the_place():
    js = WHAT_CHANGED.PAPER_JS
    # Escape leaves; focus goes to the bar's button so that the key reaches the page
    assert 'event.key === "Escape" && view.classList.contains("paper-full")' in js
    assert "expand.focus(" in js
    # the place is kept relative to the section, with scroll anchoring off meanwhile
    assert 'view.closest("section")' in js and "offset = window.scrollY - top()" in js
    assert 'root.style.overflowAnchor = "none"' in js
    assert 'root.style.overflowAnchor = ""' in js


def _two_page_site(root, pages):
    for rel, (title, body) in pages.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"<title>{title}</title><main>{body}</main>")


def test_the_overview_is_a_list_a_page_a_line_with_short_title_file_and_count(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    site = " – Asta workspace example"
    _two_page_site(
        old,
        {
            "index.html": (f"Home{site}", "<p>Same.</p>"),
            "lit/index.html": (
                f"A small review{site}",
                "<p>One two.</p><p>Three four.</p>",
            ),
            "other.html": (f"Other{site}", "<p>Five six.</p>"),
        },
    )
    _two_page_site(
        new,
        {
            "index.html": (f"Home{site}", "<p>Same.</p>"),
            "lit/index.html": (
                f"A small review{site}",
                "<p>One 2.</p><p>Three 4.</p>",
            ),
            "other.html": (f"Other{site}", "<p>Five six seven.</p>"),
        },
    )
    result = WHAT_CHANGED.build(old, new, "", "PR preview")
    assert '<p class="toc-head">This edit changed 2 things:</p>' in result
    # the site's name, which every page repeats, is taken out; the file and the count are on the line
    assert (
        '<li><a href="#p-lit-index-html">A small review</a> &middot; '
        '<code class="toc-file">lit/index.html</code> &middot; '
        '<span class="toc-count">2 changes</span></li>'
    ) in result
    assert (
        '<li><a href="#p-other-html">Other</a> &middot; '
        '<code class="toc-file">other.html</code> &middot; '
        '<span class="toc-count">1 change</span></li>'
    ) in result
    # a section's own heading keeps its full title
    assert "A small review – Asta workspace example</a>" in result


def test_the_overview_says_one_thing_and_tags_a_new_page_without_counting(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    _two_page_site(new, {"fresh.html": ("Fresh", "<p>New page.</p>")})
    result = WHAT_CHANGED.build(old, new, "", "PR preview")
    assert "This edit changed 1 thing:" in result
    assert (
        '<li><a href="#p-fresh-html">Fresh</a> <span class="tag new">new page</span>'
        ' &middot; <code class="toc-file">fresh.html</code></li>'
    ) in result
    nav = result[result.index('<nav class="toc">') : result.index("</nav>")]
    assert "toc-count" not in nav


def test_a_site_name_is_the_ending_two_pages_share_else_none():
    assert WHAT_CHANGED.site_name(["A – Site", "B – Site", "C – Other"]) == "Site"
    assert WHAT_CHANGED.site_name(["A – Site"]) is None
    assert WHAT_CHANGED.site_name(["A", "B"]) is None
    assert WHAT_CHANGED.short_title("A – Site", "Site") == "A"
    assert WHAT_CHANGED.short_title("A – Site", None) == "A – Site"
    assert WHAT_CHANGED.short_title("Site – A", "Site") == "A"
    assert WHAT_CHANGED.short_title("Slides · Site – A", "Site") == "Slides · A"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("<p>same</p>", 0),
        ("<p>a <ins>b</ins></p><p>c <del>d</del></p>", 2),
        # a block is one change however many marks it holds
        ("<p><ins>a</ins> and <del>b</del> and <ins>c</ins></p>", 1),
        # a list item holding an edited paragraph is that paragraph's change
        ("<ul><li><p>x <ins>y</ins></p></li></ul>", 1),
        # a row is one change however many cells
        ("<table><tr><td><ins>a</ins></td><td><ins>b</ins></td></tr></table>", 1),
        # a row owns the marks inside it: cells that hold paragraphs still make one
        (
            "<table><tr><td><p><ins>a</ins></p></td><td><p><ins>b</ins></p></td></tr></table>",
            1,
        ),
        # two changed rows are two changes
        (
            "<table><tr><td><p><ins>a</ins></p></td></tr>"
            "<tr><td><p><ins>b</ins></p></td></tr></table>",
            2,
        ),
        # a wholly added block, a changed link target and a changed figure count
        ('<p class="wc-block-added"><ins>whole</ins></p>', 1),
        ('<p>see <a class="wc-link-changed" href="b" data-wc-was="a">it</a></p>', 1),
        (
            '<p><del class="wc-unit"><img src="a"></del><ins class="wc-unit"><img src="b"></ins></p>',
            1,
        ),
        # a mark outside any block still counts once
        ('<div><ins class="wc-unit"><svg></svg></ins></div>', 1),
    ],
)
def test_changes_are_counted_by_the_blocks_that_hold_a_mark(body, expected):
    assert WHAT_CHANGED.count_changes(body) == expected


def test_a_changed_table_row_of_two_paragraph_cells_is_counted_once():
    # the review's fixture: the engine marks the row, and the count follows
    table = "<table><tbody><tr><td><p>{0} A</p></td><td><p>{0} B</p></td></tr></tbody></table>"
    body, changed = ENGINE.diff_content(table.format("Old"), table.format("New"))
    assert changed
    assert WHAT_CHANGED.count_changes(body) == 1


def test_no_selector_nests_has_in_has_which_a_browser_drops_whole():
    css = re.sub(r"/\*.*?\*/", "", ENGINE.DIFF_STYLE, flags=re.S)
    for selector in re.findall(r"([^{}]+)\{", css):
        stack = []
        for token in re.finditer(r"(:has\()|\(|\)", selector):
            if token.group(1):
                assert "has" not in stack, f":has inside :has in {selector.strip()}"
                stack.append("has")
            elif token.group(0) == "(":
                stack.append("(")
            elif stack:
                stack.pop()
