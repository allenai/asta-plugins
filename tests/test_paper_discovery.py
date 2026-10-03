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
    git(repo, "add", "paper", "gone", "demoted", "kept", "nested")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")

    git(repo, "rm", "gone/main.tex", "gone/latexmkrc", "demoted/latexmkrc")
    (repo / "added").mkdir()
    (repo / "added/main.tex").write_text("new")
    (repo / "added/latexmkrc").write_text("$pdf_mode = 1;\n")
    (repo / "without-rc").mkdir()
    (repo / "without-rc/main.tex").write_text("not a paper")

    assert discover(repo, base) == {
        "papers": ["added", "kept", "paper"],
        "removed": ["demoted", "gone"],
    }


def test_discovery_rejects_control_characters_in_paper_names(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    directory = repo / "bad\nname"
    directory.mkdir()
    (directory / "main.tex").write_text("paper")
    (directory / "latexmkrc").write_text("$pdf_mode = 1;\n")

    result = subprocess.run(
        ["python3", str(SCRIPT)], cwd=repo, capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "invalid paper directory name" in result.stderr
