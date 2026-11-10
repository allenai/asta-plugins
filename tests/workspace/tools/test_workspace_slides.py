"""Real renderer checks; missing tools fail this suite."""

import shutil
import subprocess

import pytest

from tests.workspace.test_workspace_slides import ASSETS, DECK, _site_with_deck, load


def test_quarto_builds_and_auto_links_multiple_nested_decks(tmp_path):
    shutil.copytree(
        ASSETS / "_extensions/asta-slides", tmp_path / "_extensions/asta-slides"
    )
    (tmp_path / "_quarto.yml").write_text(
        "project:\n  type: website\nwebsite:\n  title: Site\n  sidebar:\n    contents: auto\nformat: html\n"
    )
    (tmp_path / "index.qmd").write_text("---\ntitle: Home\n---\n\nWorkspace.\n")
    for name in ["slides/a", "slides/nested/b"]:
        folder = tmp_path / name
        folder.mkdir(parents=True)
        (folder / "slides.qmd").write_text(
            "---\ntitle: A talk\nformat: asta-slides-revealjs\n---\n\n# Section\n\n## Content\n\nText.\n"
        )
    result = subprocess.run(
        ["quarto", "render"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "[WARNING]" not in result.stderr and "WARN:" not in result.stderr
    index = (tmp_path / "_site/index.html").read_text()
    for name in ["slides/a", "slides/nested/b"]:
        assert f"{name}/slides.html" in index
        rendered = (tmp_path / "_site" / name / "slides.html").read_text()
        assert "asta-slides-section-header" in rendered
        assert "data:font/woff2" in rendered or "data:application/font-woff" in rendered


@pytest.mark.parametrize(
    "command", [["render"], ["render", "slides/workspace/slides.qmd"]]
)
def test_deck_two_folders_down_finds_site_extension(tmp_path, command):
    _site_with_deck(
        tmp_path,
        '  render:\n    - index.qmd\n    - "slides/**/slides.qmd"\n',
        DECK.format("Text."),
    )
    result = subprocess.run(
        ["quarto", *command], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "_site/slides/workspace/slides.html").exists()


def test_section_slides_false_drops_dividers_and_what_changed_numbers_as_deck(tmp_path):
    rendered = []
    for text in ["Before.", "After."]:
        _site_with_deck(tmp_path, "", DECK.format(text))
        subprocess.run(
            ["quarto", "render", "slides/workspace/slides.qmd"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        rendered.append((tmp_path / "_site/slides/workspace/slides.html").read_text())
    generator = load("what-changed")
    slides = generator.reveal_slides(rendered[1])
    assert len(slides) == 4  # title, opening, One, Two: no divider slides
    assert 'data-asta-section-name="Second"' in rendered[1]
    assert "<h1" not in "".join(slide["body"] for slide in slides[1:])
    output, _ = generator.slide_diff(*rendered, "slides.html", "slides.html")
    assert "Slide 4: Two" in output
