"""Tests for the rendered Quarto preview diff generator."""

import importlib.util
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/asta-tools/skills/workspace/assets/what-changed.py"
)
SPEC = importlib.util.spec_from_file_location("what_changed", SCRIPT)
WHAT_CHANGED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WHAT_CHANGED)


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
    assert "text-decoration: underline" in result
    assert "text-decoration: line-through" in result


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

    assert "wc-scope wc-dark" in result
