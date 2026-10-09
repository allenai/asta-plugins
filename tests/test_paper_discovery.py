"""Paper discovery keeps Quarto sections separate from preview papers."""

import json
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/asta-tools/skills/workspace/assets/paper-discovery.py"
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def discover(repo: Path, base: str = "") -> dict:
    result = subprocess.run(
        ["python3", str(SCRIPT), base], cwd=repo, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_added_removed_and_demoted_papers_and_nested_tex(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    for name in ("paper", "gone", "demoted", "kept"):
        directory = repo / name
        directory.mkdir()
        (directory / "main.tex").write_text("old")
        if name != "paper":
            (directory / "latexmkrc").write_text("$pdf_mode = 1;\n")
    (repo / "nested/sub").mkdir(parents=True)
    (repo / "nested/sub/main.tex").write_text("nested")
    (repo / "nested/sub/latexmkrc").write_text("$pdf_mode = 1;\n")
    (repo / "nested/removed").mkdir()
    (repo / "nested/removed/main.tex").write_text("removed")
    (repo / "nested/removed/latexmkrc").write_text("$pdf_mode = 1;\n")
    git(repo, "add", "paper", "gone", "demoted", "kept", "nested")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")

    git(
        repo,
        "rm",
        "gone/main.tex",
        "gone/latexmkrc",
        "demoted/latexmkrc",
        "nested/removed/main.tex",
        "nested/removed/latexmkrc",
    )
    (repo / "added").mkdir()
    (repo / "added/main.tex").write_text("new")
    (repo / "added/latexmkrc").write_text("$pdf_mode = 1;\n")
    (repo / "without-rc").mkdir()
    (repo / "without-rc/main.tex").write_text("not a paper")

    assert discover(repo, base) == {
        "papers": ["added", "kept", "nested/sub", "paper"],
        "removed": ["demoted", "gone", "nested/removed"],
        "warnings": [],
    }


def test_discovery_skips_invalid_names_but_keeps_valid_papers(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    directory = repo / "bad\nname"
    directory.mkdir()
    (directory / "main.tex").write_text("paper")
    (directory / "latexmkrc").write_text("$pdf_mode = 1;\n")
    good = repo / "paper"
    good.mkdir()
    (good / "main.tex").write_text("paper")

    result = subprocess.run(
        ["python3", str(SCRIPT)], cwd=repo, capture_output=True, text=True
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "papers": ["paper"],
        "removed": [],
        "warnings": ["Skipped invalid paper directory name: 'bad\\nname'"],
    }
    assert "Skipped invalid paper directory" in result.stderr


def test_discovery_keeps_current_papers_when_base_is_missing(tmp_path):
    repo = tmp_path / "repo"
    paper = repo / "paper"
    paper.mkdir(parents=True)
    (paper / "main.tex").write_text("paper")

    result = discover(repo, "missing-base")

    assert result["papers"] == ["paper"]
    assert result["removed"] == []
    assert result["warnings"] == [
        "Could not read paper files at base missing-base; removals were omitted"
    ]


def test_discovery_finds_single_documentclass_file_without_main_tex(tmp_path):
    repo = tmp_path / "repo"
    (repo / "paper").mkdir(parents=True)
    git(repo, "init", "-q")
    (repo / "paper/iclr2027_conference.tex").write_text(
        "% \\documentclass{commented}\n\\documentclass{article}\n"
    )
    (repo / "paper/sections.tex").write_text("no class here\n")
    (repo / "synced").mkdir()
    (repo / "synced/overleaf.json").write_text("{}")
    (repo / "synced/article.tex").write_text("\\documentclass{article}\n")
    (repo / "ambiguous").mkdir()
    (repo / "ambiguous/latexmkrc").write_text("$pdf_mode = 1;\n")
    (repo / "ambiguous/a.tex").write_text("\\documentclass{article}\n")
    (repo / "ambiguous/b.tex").write_text("\\documentclass{article}\n")
    (repo / "notes").mkdir()
    (repo / "notes/draft.tex").write_text("\\documentclass{article}\n")

    result = discover(repo)

    assert result["papers"] == ["paper", "synced"]
    assert any("ambiguous" in warning for warning in result["warnings"])
