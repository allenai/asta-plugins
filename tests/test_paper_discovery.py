"""Paper discovery keeps Quarto sections separate from preview papers."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

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
        "main_files": dict.fromkeys(
            ["added", "kept", "nested/sub", "paper"], "main.tex"
        ),
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
        "main_files": {"paper": "main.tex"},
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
    assert any(
        "ambiguous" in warning and "a.tex, b.tex" in warning
        for warning in result["warnings"]
    )


def test_removed_papers_use_the_same_main_document_rules_as_current(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    for name, marker in [
        ("paper", None),
        ("custom", "latexmkrc"),
        ("nested/paper", ".latexmkrc"),
        ("synced", "overleaf.json"),
        ("ambiguous", "latexmkrc"),
        ("sections-only", "overleaf.json"),
    ]:
        directory = tmp_path / name
        directory.mkdir(parents=True)
        if marker:
            (directory / marker).write_text("")
        (directory / "article.tex").write_text(
            "Section text" if name == "sections-only" else r"\documentclass{article}"
        )
        (directory / "section.tex").write_text(r"% \documentclass{commented}")
        if name == "ambiguous":
            (directory / "other.tex").write_text(r"\documentclass{article}")
    git(
        tmp_path,
        "add",
        "paper",
        "custom",
        "nested",
        "synced",
        "ambiguous",
        "sections-only",
    )
    git(tmp_path, "commit", "-qm", "base papers")
    base = git(tmp_path, "rev-parse", "HEAD")
    assert discover(tmp_path)["papers"] == ["custom", "nested/paper", "paper", "synced"]
    for name in ("paper", "custom", "nested", "synced", "ambiguous", "sections-only"):
        shutil.rmtree(tmp_path / name)

    result = discover(tmp_path, base)

    assert result["papers"] == []
    assert result["removed"] == ["custom", "nested/paper", "paper", "synced"]
    assert len(result["warnings"]) == 1
    assert "ambiguous" in result["warnings"][0]


def test_discovery_skips_symlinks_and_gitlinks_in_current_and_base(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "article.tex").write_text(r"\documentclass [draft]{article}")
    (paper / "main.tex").symlink_to("missing")
    (paper / "external.tex").symlink_to("article.tex")
    (paper / "lookalike.tex").write_text(r"\documentclassfoo{article}")
    git(tmp_path, "add", "paper")
    git(tmp_path, "commit", "-qm", "paper with links")
    commit = git(tmp_path, "rev-parse", "HEAD")
    git(
        tmp_path,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{commit},paper/submodule.tex",
    )
    git(tmp_path, "commit", "-qm", "paper gitlink")
    base = git(tmp_path, "rev-parse", "HEAD")

    result = discover(tmp_path, base)
    assert result["main_files"] == {"paper": "article.tex"}
    assert result["warnings"] == []
    shutil.rmtree(paper)
    result = discover(tmp_path, base)
    assert result["removed"] == ["paper"]
    assert result["warnings"] == []


@pytest.mark.parametrize("base", ["", "base"])
def test_unreadable_source_does_not_abort_main_discovery(tmp_path, monkeypatch, base):
    spec = importlib.util.spec_from_file_location("paper_discovery", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def content(path, *args, **kwargs):
        name = path.name if isinstance(path, Path) else path[-1].rsplit("/", 1)[-1]
        if name == "broken.tex":
            if base:
                raise subprocess.CalledProcessError(128, path)
            raise OSError("unreadable")
        source = r"\documentclass{article}"
        return source.encode() if base else source

    monkeypatch.setattr(Path, "read_text", content)
    monkeypatch.setattr(subprocess, "check_output", content)
    warnings = []
    assert (
        module.main_file(
            tmp_path, "paper", ["broken.tex", "article.tex"], warnings, base
        )
        == "article.tex"
    )
    assert warnings == ["Skipped unreadable paper source: paper/broken.tex"]


def test_ambiguous_base_warning_is_not_repeated(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    paper = tmp_path / "paper"
    paper.mkdir()
    for name in ("a.tex", "b.tex"):
        (paper / name).write_text(r"\documentclass{article}")
    git(tmp_path, "add", "paper")
    git(tmp_path, "commit", "-qm", "ambiguous paper")

    result = discover(tmp_path, "HEAD")
    assert result["papers"] == []
    assert len(result["warnings"]) == 1


def test_invalid_directory_is_reported_before_ambiguous_sources(tmp_path):
    paper = tmp_path / "bad\nname"
    paper.mkdir()
    (paper / "overleaf.json").write_text("{}")
    for name in ("a.tex", "b.tex"):
        (paper / name).write_text(r"\documentclass{article}")

    assert discover(tmp_path)["warnings"] == [
        "Skipped invalid paper directory name: 'bad\\nname'"
    ]
