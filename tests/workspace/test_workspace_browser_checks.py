"""Content helpers shared by the workspace's browser and comparison checks."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_comparison_instrumentation_honors_render_exclusions(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/browser"))
    spec = importlib.util.spec_from_file_location(
        "browser_differential", ROOT / "tests/browser/workspace-differential.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("index.qmd", "draft.qmd", "slides/a.qmd", "slides/private.qmd"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    assert module.render_sources(
        tmp_path, ["**/*.qmd", "!draft.qmd", "!slides/private.qmd"]
    ) == ["index.qmd", "slides/a.qmd"]


def test_report_signature_includes_page_and_live_slide_marks(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/browser"))
    from report_signature import report_signature

    (tmp_path / "what-changed.html").write_text(
        '<section class="page-diff changed" id="prose"><ins>new <em>words</em></ins><del>old</del></section>'
    )
    deck = tmp_path / "what-changed-decks/after/slides.marked.html"
    deck.parent.mkdir(parents=True)
    deck.write_text(
        '<section id="slide"><p><del>removed</del> <ins>added</ins></p></section>'
    )
    pages, marks, decks = report_signature(tmp_path)
    assert pages == {"prose"}
    assert marks == [("prose", "ins", "new words"), ("prose", "del", "old")]
    assert decks == {
        "after/slides.marked.html": [
            ("slide", "del", "removed"),
            ("slide", "ins", "added"),
        ]
    }

    original = report_signature(tmp_path)
    deck.write_text(deck.read_text().replace('id="slide"', 'id="wrong-slide"'))
    assert report_signature(tmp_path) != original
    deck.write_text(deck.read_text().replace("added", "different"))
    assert report_signature(tmp_path) != original


def test_deck_review_copy_preserves_nested_demo_assets(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/browser"))
    spec = importlib.util.spec_from_file_location(
        "browser_deck_review", ROOT / "tests/browser/deck-review.py"
    )
    review = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(review)
    site = tmp_path / "site"
    files = {
        "index.html",
        "demo/what-changed.html",
        "what-changed.html",
        "what-changed-decks/attention.marked.html",
        "what-changed-assets/theme.css",
        "slides/demo/index.html",
        "slides/attention/demo/diagram.svg",
    }
    for name in files:
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    destination = tmp_path / "copy"
    review.copy_site(site, destination)
    assert {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    } == {"index.html", "slides/demo/index.html", "slides/attention/demo/diagram.svg"}
