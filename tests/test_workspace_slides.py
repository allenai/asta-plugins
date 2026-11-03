"""Deck discovery, rendered review diffs and real Quarto website integration."""

import importlib.util
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

ASSETS = (
    Path(__file__).resolve().parents[1] / "plugins/asta-tools/skills/workspace/assets"
)


def load(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), ASSETS / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(project, *args):
    return subprocess.check_output(
        ["git", "-C", str(project), *args], text=True
    ).strip()


def test_discovers_multiple_decks_and_removals_without_entering_caches(tmp_path):
    git(tmp_path, "init", "-q")
    for directory in [
        "talks/old",
        "talks/a",
        "talks/two words",
        "_site/cached",
        ".asta/cache",
        "node_modules/pkg",
        "venv/pkg",
        "_extensions/template",
        "paper-previews/paper",
    ]:
        path = tmp_path / directory
        path.mkdir(parents=True)
        (path / "slides.qmd").write_text("# Talk\n")
    git(tmp_path, "add", "talks/old", "talks/a")
    git(
        tmp_path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "baseline",
    )
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "talks/old/slides.qmd").unlink()
    (tmp_path / "talks/link").symlink_to(tmp_path / "talks/a", target_is_directory=True)
    (tmp_path / "talks/linked-file").mkdir()
    (tmp_path / "talks/linked-file/slides.qmd").symlink_to(
        tmp_path / "talks/a/slides.qmd"
    )
    git(tmp_path / "talks", "init", "-q", "nested")
    (tmp_path / "talks/nested/slides.qmd").write_text("# Another repository\n")
    result = subprocess.check_output(
        ["python3", str(ASSETS / "paper-discovery.py"), base], cwd=tmp_path, text=True
    )
    data = json.loads(result)
    assert data["decks"] == ["talks/a", "talks/two words"]
    assert data["removed_decks"] == ["talks/old"]
    assert data["papers"] == []


def deck(*slides):
    return (
        '<html><head><title>Talk</title></head><body><div class="reveal"><div class="slides">'
        + "".join(slides)
        + "</div></div></body></html>"
    )


def slide(ident, text):
    return f'<section id="{ident}" class="slide level2"><h2>{ident}</h2><p>{text}</p></section>'


def test_changed_deck_diffs_leaf_slides_and_links_to_preview(tmp_path):
    generator = load("what-changed")
    old, new = tmp_path / "old", tmp_path / "new"
    for root in [old, new]:
        (root / "talks/a").mkdir(parents=True)
    (old / "talks/a/slides.html").write_text(
        deck(
            '<section class="stack">'
            + slide("kept", "old finding")
            + slide("gone", "Removed content")
            + "</section>"
        )
    )
    (new / "talks/a/slides.html").write_text(
        deck(
            '<section class="stack">'
            + slide("kept", "new finding")
            + slide(
                "added",
                "Added content<script>alert(1)</script><img src=x onerror=alert(2)>",
            )
            + "</section>"
        )
    )
    (new / "index.html").write_text("<main><h1>Site</h1><p>New prose</p></main>")
    output = generator.build(str(old), str(new), "https://example.org/preview", "Test")
    assert output.index("Slides · Talk") < output.index("New prose")
    assert "slides.html#/kept" in output and "slides.html#/added" in output
    assert "slides.html#/gone" not in output
    assert "<del>old</del>" in output and "<ins>new</ins>" in output
    assert "Removed content" in output and "Added content" in output
    assert "alert(1)" not in output and "onerror" not in output
    assert output.count('class="slide-diff ') == 3


def test_unchanged_deck_does_not_diff_embedded_libraries(tmp_path):
    generator = load("what-changed")
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    for root, script in [(old, "old library"), (new, "new library")]:
        (root / "slides.html").write_text(
            deck(slide("a", "Same content")) + f"<script>{script}</script>"
        )
    output = generator.build(str(old), str(new), "", "Test")
    assert "No rendered content changed" in output
    assert "new library" not in output


@pytest.mark.parametrize("removed", [False, True])
def test_added_and_removed_decks_have_one_review_section(tmp_path, removed):
    generator = load("what-changed")
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    target = old if removed else new
    (target / "slides.html").write_text(deck(slide("a", "Talk content")))
    output = generator.build(str(old), str(new), "", "Test")
    assert output.count('class="slide-diff ') == 1
    assert "Talk content" in output
    assert ('href="slides.html#/a"' in output) is not removed


@pytest.mark.skipif(not shutil.which("quarto"), reason="requires Quarto")
def test_quarto_builds_and_auto_links_multiple_nested_decks(tmp_path):
    shutil.copytree(
        ASSETS / "_extensions/asta-slides", tmp_path / "_extensions/asta-slides"
    )
    (tmp_path / "_quarto.yml").write_text(
        "project:\n  type: website\nwebsite:\n  title: Site\n  sidebar:\n    contents: auto\nformat: html\n"
    )
    (tmp_path / "index.qmd").write_text("---\ntitle: Home\n---\n\nWorkspace.\n")
    for name in ["talks/a", "talks/nested/b"]:
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
    for name in ["talks/a", "talks/nested/b"]:
        assert f"{name}/slides.html" in index
        rendered = (tmp_path / "_site" / name / "slides.html").read_text()
        assert "asta-slides-section-header" in rendered
        assert "data:font/woff2" in rendered or "data:application/font-woff" in rendered


@pytest.mark.skipif(not shutil.which("make"), reason="requires make")
@pytest.mark.parametrize("rules", ["workspace.mk", "Makefile"])
def test_workspace_fetches_slides_from_selected_ref_and_preserves_ejected_copy(
    tmp_path, rules
):
    source = tmp_path / "release/plugins/asta-tools/skills/workspace/assets/_extensions"
    for name in ["evidence", "asta-slides"]:
        shutil.copytree(ASSETS / "_extensions" / name, source / name)
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source.parents[5], arcname="release")
    project = tmp_path / "project"
    (project / "talks/a").mkdir(parents=True)
    (project / "talks/a/slides.qmd").write_text("format: asta-slides-revealjs\n")
    git(project, "init", "-q")

    def install():
        subprocess.run(
            ["make", "-f", str(ASSETS / rules), "workspace-assets"],
            cwd=project,
            env={**os.environ, "ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri()},
            check=True,
            capture_output=True,
        )

    install()
    extension = project / "_extensions/asta-slides/_extension.yml"
    assert "self-contained-math: true" in extension.read_text()
    extension.write_text(extension.read_text() + "# Ejected\n")
    git(project, "add", "_extensions/asta-slides/_extension.yml")
    install()
    assert extension.read_text().endswith("# Ejected\n")
