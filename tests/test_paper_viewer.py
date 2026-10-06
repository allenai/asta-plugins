import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ASSETS = Path("plugins/asta-tools/skills/workspace/assets").resolve()
SCRIPT = ASSETS / "paper-viewer.py"


def generate(root, *papers):
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=root,
        input=json.dumps({"papers": list(papers)}),
        capture_output=True,
        text=True,
    )


def test_multiple_and_nested_viewers_link_the_matching_artifacts(tmp_path):
    assert generate(tmp_path, "paper", "research/other paper").returncode == 0
    paper = (tmp_path / "paper/html/index.qmd").read_text()
    nested = (tmp_path / "research/other paper/html/index.qmd").read_text()
    assert 'data-paper-preview="../../paper-previews/paper"' in paper
    assert (
        'data-paper-preview="../../../paper-previews/research/other%20paper"' in nested
    )
    assert (
        "sandbox', 'allow-same-origin allow-popups allow-popups-to-escape-sandbox'"
        in nested
    )
    assert "allow-scripts" not in nested
    assert "if (!response.ok) return" in nested
    assert "use the PDF link when available" in nested


@pytest.mark.parametrize("suffix", ["qmd", "md", "html"])
def test_project_viewer_wins(tmp_path, suffix):
    folder = tmp_path / "paper/html"
    folder.mkdir(parents=True)
    custom = folder / f"index.{suffix}"
    custom.write_text("custom")
    assert generate(tmp_path, "paper").returncode == 0
    assert custom.read_text() == "custom"
    assert list(folder.iterdir()) == [custom]


def test_symlinked_viewer_is_preserved(tmp_path):
    folder = tmp_path / "paper/html"
    folder.mkdir(parents=True)
    target = tmp_path / "missing"
    (folder / "index.qmd").symlink_to(target)
    assert generate(tmp_path, "paper").returncode == 0
    assert not target.exists()
    assert (folder / "index.qmd").is_symlink()


def test_generated_viewer_refreshes_and_is_removed_after_paper_moves(tmp_path):
    assert generate(tmp_path, "paper").returncode == 0
    old = tmp_path / "paper/html/index.qmd"
    current = old.read_text()
    old.write_text(current.replace("The preview builds PDF and HTML", "Old template"))
    assert generate(tmp_path, "paper").returncode == 0
    assert old.read_text() == current
    assert generate(tmp_path, "papers/moved").returncode == 0
    assert not old.exists()
    moved = tmp_path / "papers/moved/html/index.qmd"
    assert moved.is_file()
    assert generate(tmp_path).returncode == 0
    assert not moved.exists()


def test_committed_generated_viewer_becomes_user_owned(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert generate(tmp_path, "paper").returncode == 0
    page = tmp_path / "paper/html/index.qmd"
    subprocess.run(["git", "add", "paper/html/index.qmd"], cwd=tmp_path, check=True)
    page.write_text(page.read_text() + "\nUser customization\n")
    custom = page.read_text()
    assert generate(tmp_path, "paper").returncode == 0
    assert page.read_text() == custom
    assert generate(tmp_path).returncode == 0
    assert page.read_text() == custom


def test_orphan_cleanup_preserves_custom_and_symlinked_pages(tmp_path):
    assert generate(tmp_path, "paper").returncode == 0
    folder = tmp_path / "paper/html"
    source = folder / "index.qmd"
    source.rename(tmp_path / "generated.qmd")
    source.symlink_to(tmp_path / "generated.qmd")
    custom = tmp_path / "custom/html/index.qmd"
    custom.parent.mkdir(parents=True)
    custom.write_text("Custom page")
    link = tmp_path / "linked"
    link.symlink_to(folder, target_is_directory=True)
    assert generate(tmp_path).returncode == 0
    assert source.is_symlink()
    assert (tmp_path / "generated.qmd").exists()
    assert custom.read_text() == "Custom page"


@pytest.mark.parametrize(
    "directory",
    [
        "../outside",
        "/absolute",
        "paper/../other",
        "paper/./other",
        "paper//other",
        "",
        1,
        None,
    ],
)
def test_invalid_path_is_rejected(tmp_path, directory):
    assert generate(tmp_path, directory).returncode != 0
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "data",
    [
        {},
        [],
        {"papers": "paper"},
        {"papers": None},
        {"papers": ["paper", "../outside"]},
    ],
)
def test_invalid_discovery_does_not_partially_generate(tmp_path, data):
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        input=json.dumps(data),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "paper-viewer:" in result.stderr
    assert "Traceback" not in result.stderr
    assert not list(tmp_path.iterdir())


def test_paper_titles_and_html_are_escaped(tmp_path):
    name = 'other<>&"'
    assert generate(tmp_path, name).returncode == 0
    document = (tmp_path / name / "html/index.qmd").read_text()
    metadata = yaml.safe_load(document.split("---")[1])
    assert metadata["title"] == name + " HTML"
    assert "<code>other&lt;&gt;&amp;&quot;/main.tex</code>" in document
    assert 'data-paper-preview="../../paper-previews/other%3C%3E%26%22"' in document
    assert "\\u003c" in document


@pytest.mark.skipif(not shutil.which("quarto"), reason="needs the workspace image")
@pytest.mark.parametrize("directory", ["paper", "papers/special*[x]`other"])
def test_quarto_renders_the_managed_viewer(tmp_path, directory):
    assert generate(tmp_path, directory).returncode == 0
    (tmp_path / "_quarto.yml").write_text(
        yaml.safe_dump(
            {
                "project": {
                    "type": "website",
                    "render": ["**/*.qmd"],
                },
                "format": "html",
            }
        )
    )
    result = subprocess.run(
        ["quarto", "render"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    page = (tmp_path / f"_site/{directory}/html/index.html").read_text()
    assert "const host = document.querySelector" in page
    assert 'href="../../paper-previews/paper/main.pdf"' not in page
    assert "createElement('iframe')" in page
    assert f"<code>{directory}/main.tex</code>" in page


def test_workflow_generates_before_render_without_changing_tracked_sources(tmp_path):
    workflow = yaml.load(
        Path(".github/workflows/workspace-quarto-site.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    steps = workflow["jobs"]["build"]["steps"]
    step = next(
        s for s in steps if s.get("name") == "Generate managed paper viewer pages"
    )
    assert steps.index(step) < next(
        i for i, s in enumerate(steps) if s.get("name") == "Run docs checks"
    )
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("/paper/html/index.qmd\n")
    (tmp_path / "paper").mkdir()
    (tmp_path / "paper/main.tex").write_text("source")
    (tmp_path / "scripts").mkdir()
    for name in ("paper-discovery.py", "paper-viewer.py"):
        (tmp_path / "scripts" / name).write_text((ASSETS / name).read_text())
    subprocess.run(
        [
            "git",
            "add",
            ".gitignore",
            "paper/main.tex",
            "scripts/paper-discovery.py",
            "scripts/paper-viewer.py",
        ],
        cwd=tmp_path,
        check=True,
    )
    script = step["run"].replace("${{ job.workflow_repository }}", "unused")
    script = script.replace("${{ job.workflow_sha }}", "unused")
    status_command = ["git", "status", "--porcelain", "--untracked-files=all"]
    before = subprocess.check_output(status_command, cwd=tmp_path)
    result = subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "paper/html/index.qmd").exists()
    assert subprocess.check_output(status_command, cwd=tmp_path) == before
    assert not list(tmp_path.glob("tmp.*"))

    (tmp_path / ".gitignore").write_text("")
    subprocess.run(["git", "add", "paper/html/index.qmd"], cwd=tmp_path, check=True)
    custom = tmp_path / "paper/html/index.qmd"
    custom.write_text("custom")
    assert generate(tmp_path, "paper").returncode == 0
    assert custom.read_text() == "custom"
