"""`asta workspace what-changed` compares a git ref's rendered site with the working tree."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from asta.commands.workspace import workspace

ASSETS = Path(__file__).parent.parent / "plugins/asta-tools/skills/workspace/assets"

# Stands in for `make render` -> `quarto render`: wraps index.qmd in the
# <main> Quarto emits, so the test needs neither make nor Quarto.
FAKE_MAKE = """#!/usr/bin/env python3
import pathlib, sys
assert sys.argv[1:] == ["render"], sys.argv
paras = "".join(f"<p>{line}</p>" for line in open("index.qmd").read().splitlines())
pathlib.Path("_site").mkdir(exist_ok=True)
pathlib.Path("_site/index.html").write_text(
    f"<html><head><title>Report</title></head><body><main>{paras}</main></body></html>"
)
"""


def git(project: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=project,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def project(
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    bin_dir = tmp_path_factory.mktemp("bin")
    (bin_dir / "make").write_text(FAKE_MAKE)
    (bin_dir / "make").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    (tmp_path / ".gitignore").write_text("_site/\n.asta/cache/\n")
    (tmp_path / "scripts").mkdir()
    shutil.copy(ASSETS / "what-changed.py", tmp_path / "scripts/what-changed.py")
    (tmp_path / "index.qmd").write_text("The baseline finding holds.\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "first")
    git(tmp_path, "tag", "last-read")
    return tmp_path


def test_highlights_edit_since_ref(project: Path) -> None:
    (project / "index.qmd").write_text(
        "The baseline finding holds.\nA newly drafted paragraph.\n"
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    page = (project / "_site/what-changed.html").read_text()
    assert "Changes since last-read" in page
    assert "<ins" in page and "newly drafted paragraph" in page
    worktrees = subprocess.run(
        ["git", "worktree", "list"], cwd=project, capture_output=True, text=True
    ).stdout
    assert len(worktrees.strip().splitlines()) == 1


def test_unknown_ref(project: Path) -> None:
    result = CliRunner().invoke(
        workspace, ["what-changed", "no-such-ref", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "Unknown git ref: no-such-ref" in result.output


@pytest.mark.parametrize("output_name", ["what-changed.html", "custom.html"])
def test_repeat_run_excludes_previous_report(project: Path, output_name: str) -> None:
    # This project override has no built-in recognition of generated reports.
    (project / "scripts/what-changed.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "site = Path(sys.argv[sys.argv.index('--new') + 1])\n"
        "out = Path(sys.argv[sys.argv.index('--out') + 1])\n"
        "pages = sorted(p.relative_to(site).as_posix() for p in site.rglob('*.html'))\n"
        "out.write_text('<html><body>' + ', '.join(pages) + '</body></html>')\n"
    )
    out = project / "_site" / output_name
    args = ["what-changed", "last-read", "--project", str(project)]
    if output_name != "what-changed.html":
        args += ["--out", str(out)]
    for _ in range(2):
        result = CliRunner().invoke(workspace, args)
        assert result.exit_code == 0, result.output
        assert out.read_text() == "<html><body>index.html</body></html>"


@pytest.mark.parametrize("stale_output", [False, True])
@pytest.mark.parametrize(
    "script",
    [
        "# Exit successfully without writing a report.\n",
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[sys.argv.index('--out') + 1]).write_text('')\n",
    ],
    ids=["no-output", "empty-output"],
)
def test_requires_fresh_nonempty_html(
    project: Path, stale_output: bool, script: str
) -> None:
    (project / "scripts/what-changed.py").write_text(script)
    if stale_output:
        (project / "_site").mkdir()
        (project / "_site/what-changed.html").write_text("A stale report")
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "did not write nonempty HTML" in result.output
    assert "Wrote " not in result.output
    assert "open http" not in result.output
    worktrees = subprocess.run(
        ["git", "worktree", "list"], cwd=project, capture_output=True, text=True
    ).stdout
    assert len(worktrees.strip().splitlines()) == 1


def test_requires_a_diff_script(project: Path) -> None:
    git(project, "rm", "-q", "scripts/what-changed.py")
    (project / "workspace.mk").write_text("")
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "No what-changed.py for this project" in result.output


def test_template_with_real_quarto(tmp_path: Path) -> None:
    source = os.environ.get("ASTA_TEST_WORKSPACE_TEMPLATE")
    if not source:
        pytest.skip("Set ASTA_TEST_WORKSPACE_TEMPLATE to a workspace-template checkout")
    assert shutil.which("make") and shutil.which("quarto")
    project = tmp_path / "project"
    shutil.copytree(source, project, ignore=shutil.ignore_patterns(".git"))
    repo = ASSETS.parents[4]
    ref = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    workflow = project / ".github/workflows/docs.yml"
    workflow.write_text(
        re.sub(
            r"(uses: allenai/asta-plugins/\.github/workflows/workspace-quarto-site\.yml@)\S+",
            rf"\g<1>{ref}",
            workflow.read_text(),
        )
    )
    files = subprocess.check_output(
        ["git", "-C", source, "ls-files"], text=True
    ).splitlines()
    git(project, "init", "-q")
    git(project, "add", *files)
    git(project, "commit", "-qm", "template baseline")
    git(project, "tag", "last-read")
    with (project / "index.qmd").open("a") as page:
        page.write("\nA newly drafted paragraph for local comparison.\n")
    for _ in range(2):
        result = CliRunner().invoke(
            workspace, ["what-changed", "last-read", "--project", str(project)]
        )
        assert result.exit_code == 0, result.output
        report = (project / "_site/what-changed.html").read_text()
        assert re.search(r"<ins\b[^>]*>[^<]*newly drafted paragraph", report)
        assert "http://localhost:4848/what-changed.html" in result.output
        assert 'href="#what-changed-html"' not in report
    manifest = json.loads((project / ".asta/cache/workspace.json").read_text())
    assert manifest["ref"] == ref
    assert "what-changed.py" in manifest["scripts"]
