"""`asta workspace what-changed` compares a git ref's rendered site with the working tree."""

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from asta.commands import workspace as workspace_module
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


@pytest.mark.parametrize("explicit_project", [False, True])
def test_subdirectory_uses_matching_baseline(
    project: Path, monkeypatch: pytest.MonkeyPatch, explicit_project: bool
) -> None:
    nested = project / "research workspace" / "docs"
    nested.mkdir(parents=True)
    (project / "index.qmd").rename(nested / "index.qmd")
    (project / "scripts").rename(nested / "scripts")
    # A valid but unrelated root site makes a wrong-directory render succeed.
    (project / "index.qmd").write_text("Unrelated repository-root page.\n")
    git(project, "add", "index.qmd", "scripts", "research workspace")
    git(project, "commit", "-qm", "nest workspace")
    git(project, "tag", "-f", "last-read")
    (nested / "index.qmd").write_text(
        "The baseline finding holds.\nA newly drafted paragraph.\n"
    )
    args = ["what-changed", "last-read"]
    if explicit_project:
        monkeypatch.chdir(project)
        args += ["--project", "research workspace/docs"]
    else:
        monkeypatch.chdir(nested)
    result = CliRunner().invoke(workspace, args)
    assert result.exit_code == 0, result.output
    report = (nested / "_site/what-changed.html").read_text()
    assert "<ins" in report and "newly drafted paragraph" in report
    assert "Unrelated repository-root page" not in report
    page_diff = re.search(
        r'<section class="page-diff changed".*?</section>', report, re.S
    )
    assert page_diff and "<del" not in page_diff.group()


def test_baseline_missing_ignored_input_reports_build_stderr(
    project: Path,
) -> None:
    (project / ".gitignore").write_text("_site/\n.asta/cache/\ninputs.csv\n")
    git(project, "add", ".gitignore")
    git(project, "commit", "-qm", "ignore local inputs")
    git(project, "tag", "-f", "last-read")
    (project / "inputs.csv").write_text("local-only data")
    Path(shutil.which("make")).write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "if not pathlib.Path('inputs.csv').exists():\n"
        "    print('Missing local inputs.csv for render', file=sys.stderr)\n"
        "    sys.exit(2)\n" + FAKE_MAKE
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "'make render' failed for last-read" in result.output
    assert "Missing local inputs.csv for render" in result.output
    assert "Wrote " not in result.output
    worktrees = subprocess.check_output(
        ["git", "-C", str(project), "worktree", "list"], text=True
    )
    assert len(worktrees.strip().splitlines()) == 1


def test_cleanup_failure_warns_without_hiding_report(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = workspace_module._git

    def fail_removal(directory, *args):
        if args[:2] == ("worktree", "remove"):
            return subprocess.CompletedProcess(args, 1, stderr="worktree is locked")
        return original(directory, *args)

    monkeypatch.setattr(workspace_module, "_git", fail_removal)
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    assert (project / "_site/what-changed.html").is_file()
    assert (
        "Warning: baseline worktree cleanup failed: worktree is locked" in result.output
    )
    worktrees = subprocess.check_output(
        ["git", "-C", str(project), "worktree", "list"], text=True
    )
    assert len(worktrees.strip().splitlines()) == 1


def test_unknown_ref(project: Path) -> None:
    result = CliRunner().invoke(
        workspace, ["what-changed", "no-such-ref", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "Unknown git ref: no-such-ref" in result.output


def test_project_outside_git_reports_repository_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        workspace, ["what-changed", "HEAD", "--project", str(tmp_path)]
    )
    assert result.exit_code != 0
    assert "Not a git repository:" in result.output
    assert "Unknown git ref" not in result.output


def test_missing_git_reports_required_tool(project: Path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", "")
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "git is required" in result.output


def test_option_like_ref_is_not_a_git_option(project: Path) -> None:
    commit = subprocess.check_output(
        ["git", "-C", str(project), "rev-parse", "HEAD"], text=True
    ).strip()
    git(project, "update-ref", "refs/tags/-last-read", commit)
    result = CliRunner().invoke(
        workspace,
        ["what-changed", "--project", str(project), "--", "-last-read"],
    )
    assert result.exit_code == 0, result.output
    assert (
        "Changes since -last-read" in (project / "_site/what-changed.html").read_text()
    )


@pytest.mark.parametrize("external", [False, True])
def test_unrecognized_file_outside_site_is_preserved(
    project: Path, external: bool
) -> None:
    out = (
        project.parent / f"{project.name}-saved.html"
        if external
        else project / "index.qmd"
    )
    previous = "Keep this external file" if external else out.read_text()
    if external:
        out.write_text(previous)
    result = CliRunner().invoke(
        workspace,
        ["what-changed", "last-read", "--project", str(project), "--out", str(out)],
    )
    assert result.exit_code != 0
    assert "Refusing to overwrite an unrecognized file" in result.output
    assert out.read_text() == previous
    assert "Wrote " not in result.stdout


@pytest.mark.parametrize("external", [False, True])
def test_generated_report_outside_site_can_be_updated(
    project: Path, external: bool
) -> None:
    out = (
        project.parent / f"{project.name}-saved.html"
        if external
        else project / "saved.html"
    )
    args = ["what-changed", "last-read", "--project", str(project), "--out", str(out)]
    first = CliRunner().invoke(workspace, args)
    assert first.exit_code == 0, first.output
    with (project / "index.qmd").open("a") as page:
        page.write("A later finding.\n")
    second = CliRunner().invoke(workspace, args)
    assert second.exit_code == 0, second.output
    assert "A later finding" in out.read_text()
    out.write_text("An unrelated replacement")
    third = CliRunner().invoke(workspace, args)
    assert third.exit_code != 0
    assert out.read_text() == "An unrelated replacement"


def test_preview_url_encodes_output_path(project: Path) -> None:
    out = project / "_site/reports/new finding #1.html"
    result = CliRunner().invoke(
        workspace,
        ["what-changed", "last-read", "--project", str(project), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert "http://localhost:4848/reports/new%20finding%20%231.html" in result.stdout


@pytest.mark.parametrize("previous_report", [False, True])
def test_custom_script_never_sees_output_staging_directory(
    project: Path, previous_report: bool
) -> None:
    args = ["what-changed", "last-read", "--project", str(project)]
    if previous_report:
        first = CliRunner().invoke(workspace, args)
        assert first.exit_code == 0, first.output
    (project / "scripts/what-changed.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "site = Path(sys.argv[sys.argv.index('--new') + 1])\n"
        "out = Path(sys.argv[sys.argv.index('--out') + 1])\n"
        "assert not list(site.rglob('.asta-what-changed-*'))\n"
        "out.write_text('<html>Clean comparison inputs</html>')\n"
    )
    result = CliRunner().invoke(workspace, args)
    assert result.exit_code == 0, result.output
    assert (
        project / "_site/what-changed.html"
    ).read_text() == "<html>Clean comparison inputs</html>"


def test_diff_failure_names_selected_script_and_exit_code(project: Path) -> None:
    script = project / "scripts/what-changed.py"
    script.write_text("import sys\nsys.exit(7)\n")
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert f"what-changed.py failed (exit 7): {script}" in result.output


def test_custom_script_changes_to_snapshot_leave_rendered_pages_intact(
    project: Path,
) -> None:
    (project / "scripts/what-changed.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "site = Path(sys.argv[sys.argv.index('--new') + 1])\n"
        "out = Path(sys.argv[sys.argv.index('--out') + 1])\n"
        "(site / 'index.html').write_text('Modified comparison input')\n"
        "out.write_text('<html>Comparison report</html>')\n"
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    assert "The baseline finding holds" in (project / "_site/index.html").read_text()


@pytest.mark.parametrize("previous_report", [False, True])
def test_cleanup_interruption_leaves_report_recognized(
    project: Path, monkeypatch, previous_report: bool
) -> None:
    original = workspace_module._git

    def interrupt_removal(directory, *args):
        if args[:2] == ("worktree", "remove"):
            raise KeyboardInterrupt
        return original(directory, *args)

    args = ["what-changed", "last-read", "--project", str(project)]
    if previous_report:
        first = CliRunner().invoke(workspace, args)
        assert first.exit_code == 0, first.output
        with (project / "index.qmd").open("a") as page:
            page.write("A later finding.\n")
    with monkeypatch.context() as patch:
        patch.setattr(workspace_module, "_git", interrupt_removal)
        result = CliRunner().invoke(workspace, args)
        assert result.exit_code != 0
    assert (project / "_site/what-changed.html").is_file()
    # The next comparison must neither include the old report nor reject its destination.
    second = CliRunner().invoke(workspace, args)
    assert second.exit_code == 0, second.output


def test_baseline_directory_cleanup_failure_warns_and_keeps_report(
    project: Path, monkeypatch
) -> None:
    original = workspace_module.tempfile.TemporaryDirectory.cleanup

    def fail_cleanup(temporary):
        original(temporary)
        if Path(temporary.name).name.startswith("asta-what-changed-"):
            raise PermissionError("baseline cleanup denied")

    args = ["what-changed", "last-read", "--project", str(project)]
    with monkeypatch.context() as patch:
        patch.setattr(
            workspace_module.tempfile.TemporaryDirectory, "cleanup", fail_cleanup
        )
        result = CliRunner().invoke(workspace, args)
        assert result.exit_code == 0, result.output
        assert (
            "Warning: baseline directory cleanup failed: baseline cleanup denied"
            in result.stderr
        )
        assert "Wrote " in result.stdout
    second = CliRunner().invoke(workspace, args)
    assert second.exit_code == 0, second.output


@pytest.mark.parametrize("previous_report", [False, True])
def test_state_write_failure_does_not_publish_report(
    project: Path, monkeypatch, previous_report: bool
) -> None:
    args = ["what-changed", "last-read", "--project", str(project)]
    out = project / "_site/what-changed.html"
    if previous_report:
        first = CliRunner().invoke(workspace, args)
        assert first.exit_code == 0, first.output
    previous = out.read_bytes() if out.exists() else None
    with (project / "index.qmd").open("a") as page:
        page.write("A later finding.\n")

    def fail_state_write(*args):
        raise PermissionError("state write denied")

    with monkeypatch.context() as patch:
        patch.setattr(workspace_module, "_atomic_write", fail_state_write)
        result = CliRunner().invoke(workspace, args)
        assert result.exit_code != 0
    if previous is None:
        assert not out.exists()
    else:
        assert out.read_bytes() == previous
    assert "Wrote " not in result.stdout
    second = CliRunner().invoke(workspace, args)
    assert second.exit_code == 0, second.output


@pytest.mark.parametrize("previous_report", [False, True])
@pytest.mark.parametrize("failure", [KeyboardInterrupt, PermissionError])
def test_interrupted_publication_recognizes_old_or_new_report(
    project: Path, monkeypatch, previous_report: bool, failure
) -> None:
    args = ["what-changed", "last-read", "--project", str(project)]
    out = project / "_site/what-changed.html"
    if previous_report:
        first = CliRunner().invoke(workspace, args)
        assert first.exit_code == 0, first.output
    previous = out.read_bytes() if out.exists() else None
    with (project / "index.qmd").open("a") as page:
        page.write("A later finding.\n")
    original = Path.replace

    def interrupt_publish(path, target):
        if Path(target) == out:
            raise failure
        return original(path, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", interrupt_publish)
        result = CliRunner().invoke(workspace, args)
        assert result.exit_code != 0
    if previous is None:
        assert not out.exists()
    else:
        assert out.read_bytes() == previous
    second = CliRunner().invoke(workspace, args)
    assert second.exit_code == 0, second.output


@pytest.mark.parametrize(
    "output_names",
    [
        ["what-changed.html", "what-changed.html"],
        ["custom.html", "custom.html"],
        ["custom.html", "what-changed.html", "another.html", "custom.html"],
        ["reports/custom.html", "what-changed.html"],
    ],
)
def test_repeat_run_excludes_previous_report(
    project: Path, output_names: list[str]
) -> None:
    # This project override has no built-in recognition of generated reports.
    (project / "scripts/what-changed.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "site = Path(sys.argv[sys.argv.index('--new') + 1])\n"
        "out = Path(sys.argv[sys.argv.index('--out') + 1])\n"
        "pages = sorted(p.relative_to(site).as_posix() for p in site.rglob('*.html'))\n"
        "out.write_text('<html><body>' + ', '.join(pages) + '</body></html>')\n"
    )
    for output_name in output_names:
        out = project / "_site" / output_name
        args = ["what-changed", "last-read", "--project", str(project)]
        if output_name != "what-changed.html":
            args += ["--out", str(out)]
        result = CliRunner().invoke(workspace, args)
        assert result.exit_code == 0, result.output
        assert out.read_text() == "<html><body>index.html</body></html>"
    for output_name in output_names:
        assert (project / "_site" / output_name).is_file()


def test_renderer_replacement_of_report_is_compared(project: Path) -> None:
    args = ["what-changed", "last-read", "--project", str(project)]
    result = CliRunner().invoke(
        workspace, [*args, "--out", str(project / "_site/custom.html")]
    )
    assert result.exit_code == 0, result.output
    Path(shutil.which("make")).write_text(
        FAKE_MAKE + "\nif pathlib.Path('.git').is_dir():\n"
        "    pathlib.Path('_site/custom.html').write_text("
        "'<html><body><main>Real rendered page.</main></body></html>')\n"
    )
    result = CliRunner().invoke(workspace, args)
    assert result.exit_code == 0, result.output
    report = (project / "_site/what-changed.html").read_text()
    assert 'href="#p-custom-html"' in report
    assert "Real rendered page" in report
    assert "Real rendered page" in (project / "_site/custom.html").read_text()


@pytest.mark.parametrize("output_name", ["what-changed.html", "custom.html"])
@pytest.mark.parametrize("existing_target", [False, True])
def test_symlink_output_preserves_external_target(
    project: Path, output_name: str, existing_target: bool
) -> None:
    target = project.parent / "external.html"
    if existing_target:
        target.write_text("Keep this file")
    (project / "_site").mkdir()
    output = project / "_site" / output_name
    output.symlink_to(target)
    args = ["what-changed", "last-read", "--project", str(project)]
    if output_name != "what-changed.html":
        args += ["--out", str(output)]
    result = CliRunner().invoke(workspace, args)
    assert result.exit_code != 0
    assert "must not use symlinks" in result.output
    assert "Wrote " not in result.output
    assert output.is_symlink()
    if existing_target:
        assert target.read_text() == "Keep this file"
    else:
        assert not target.exists()


def test_symlink_created_during_render_preserves_target(project: Path) -> None:
    target = project.parent / "external.html"
    target.write_text("Keep this file")
    Path(shutil.which("make")).write_text(
        FAKE_MAKE
        + "\npathlib.Path('_site/what-changed.html').symlink_to("
        + repr(str(target))
        + ")\n"
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "must not use symlinks" in result.output
    assert target.read_text() == "Keep this file"
    assert (project / "_site/what-changed.html").is_symlink()
    worktrees = subprocess.check_output(
        ["git", "-C", str(project), "worktree", "list"], text=True
    )
    assert len(worktrees.strip().splitlines()) == 1


def test_symlink_site_preserves_external_directory(project: Path) -> None:
    target = project.parent / "external-site"
    target.mkdir()
    report = target / "what-changed.html"
    report.write_text("Keep this file")
    (project / "_site").symlink_to(target, target_is_directory=True)
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "must not use symlinks" in result.output
    assert report.read_text() == "Keep this file"
    assert list(target.iterdir()) == [report]


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
        state = project / workspace_module.DIFF_STATE
        state.parent.mkdir(parents=True)
        state.write_text(
            json.dumps(
                {"what-changed.html": hashlib.sha256(b"A stale report").hexdigest()}
            )
        )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "did not write nonempty HTML" in result.output
    assert "Wrote " not in result.output
    assert "open http" not in result.output
    output = project / "_site/what-changed.html"
    if stale_output:
        assert output.read_text() == "A stale report"
    else:
        assert not output.exists()
    worktrees = subprocess.run(
        ["git", "worktree", "list"], cwd=project, capture_output=True, text=True
    ).stdout
    assert len(worktrees.strip().splitlines()) == 1


@pytest.mark.parametrize("external_output", [False, True])
@pytest.mark.parametrize("symlink_output", [False, True])
def test_failed_comparison_preserves_previous_report(
    project: Path, external_output: bool, symlink_output: bool
) -> None:
    output = (
        project.parent / f"{project.name}-saved-report.html"
        if external_output
        else project / "_site/custom.html"
    )
    args = [
        "what-changed",
        "last-read",
        "--project",
        str(project),
        "--out",
        str(output),
    ]
    result = CliRunner().invoke(workspace, args)
    assert result.exit_code == 0, result.output
    previous = output.read_bytes()
    state = project / workspace_module.DIFF_STATE
    previous_state = state.read_bytes() if state.exists() else None
    target = project.parent / "keep.html"
    target.write_text("Keep this file")
    (project / "scripts/what-changed.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "out = Path(sys.argv[sys.argv.index('--out') + 1])\n"
        + (
            f"out.symlink_to({str(target)!r})\n"
            if symlink_output
            else "out.write_text('Partial report')\nsys.exit(1)\n"
        )
    )
    result = CliRunner().invoke(workspace, args)
    assert result.exit_code != 0
    assert "Wrote " not in result.output
    assert output.read_bytes() == previous
    assert target.read_text() == "Keep this file"
    assert not list(output.parent.glob(".asta-what-changed-*"))
    if previous_state is not None:
        assert state.read_bytes() == previous_state


def test_requires_a_diff_script(project: Path, monkeypatch) -> None:
    git(project, "rm", "-q", "scripts/what-changed.py")
    (project / "workspace.mk").write_text("")
    monkeypatch.setattr(
        workspace_module, "load_asset", lambda *_: pytest.fail("unexpected fetch")
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "No what-changed.py for this project" in result.output


@pytest.mark.parametrize("output_name", ["what-changed.html", "custom.html"])
@pytest.mark.parametrize("previous_report", [False, True])
def test_rendered_destination_is_preserved(
    project: Path, output_name: str, previous_report: bool
) -> None:
    out = project / "_site" / output_name
    args = ["what-changed", "last-read", "--project", str(project)]
    if output_name != "what-changed.html":
        args += ["--out", str(out)]
    if previous_report:
        result = CliRunner().invoke(workspace, args)
        assert result.exit_code == 0, result.output
    state = project / workspace_module.DIFF_STATE
    previous_state = state.read_bytes() if state.exists() else None
    page = "<html><body><main>A real research page.</main></body></html>"
    Path(shutil.which("make")).write_text(
        FAKE_MAKE + f"\npathlib.Path('_site/{output_name}').write_text({page!r})\n"
    )
    result = CliRunner().invoke(workspace, args)
    assert result.exit_code != 0
    assert "Refusing to overwrite an unrecognized site page" in result.output
    assert "Choose a different --out" in result.output
    assert out.read_text() == page
    assert "Wrote " not in result.stdout
    if previous_state is not None:
        assert state.read_bytes() == previous_state
    else:
        assert not state.exists()
    assert (
        len(
            subprocess.check_output(
                ["git", "-C", str(project), "worktree", "list"], text=True
            ).splitlines()
        )
        == 1
    )


def test_render_progress_is_visible_before_build_finishes(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Path(shutil.which("make")).write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys, time\n"
        "release = pathlib.Path.cwd() / 'release-render'\n"
        "print('render-progress:' + str(release), flush=True)\n"
        "deadline = time.monotonic() + 3\n"
        "while not release.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "if not release.exists():\n"
        "    sys.exit('Progress was buffered until render finished')\n" + FAKE_MAKE
    )
    original = workspace_module.click.echo
    progress = []

    def receive_progress(message=None, *args, **kwargs):
        original(message, *args, **kwargs)
        if isinstance(message, str) and message.startswith("render-progress:"):
            assert kwargs.get("err") is True
            progress.append(message)
            Path(message.strip().removeprefix("render-progress:")).touch()

    monkeypatch.setattr(workspace_module.click, "echo", receive_progress)
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    assert len(progress) == 2
    assert "render-progress:" not in result.stdout


@pytest.mark.parametrize("inside_site", [False, True])
def test_symlinked_external_parent_allows_output(
    project: Path, inside_site: bool
) -> None:
    parent = project.parent / (project.name + "-linked-parent")
    parent.symlink_to(
        project if inside_site else project.parent, target_is_directory=True
    )
    out = (
        parent / "_site/changes.html"
        if inside_site
        else parent / f"{project.name}-saved.html"
    )
    result = CliRunner().invoke(
        workspace,
        ["what-changed", "last-read", "--project", str(project), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert "Changes since last-read" in out.read_text()


@pytest.mark.parametrize("project_alias", [False, True])
def test_symlinked_site_subdirectory_preserves_target(
    project: Path, project_alias: bool
) -> None:
    target = project.parent / (project.name + "-external-reports")
    target.mkdir()
    (target / "custom.html").write_text("Keep this file")
    (project / "_site").mkdir()
    (project / "_site/reports").symlink_to(target, target_is_directory=True)
    output_project = project
    if project_alias:
        output_project = project.parent / (project.name + "-alias")
        output_project.symlink_to(project, target_is_directory=True)
    result = CliRunner().invoke(
        workspace,
        [
            "what-changed",
            "last-read",
            "--project",
            str(project),
            "--out",
            str(output_project / "_site/reports/custom.html"),
        ],
    )
    assert result.exit_code != 0
    assert "must not use symlinks" in result.output
    assert (target / "custom.html").read_text() == "Keep this file"


@pytest.mark.parametrize(
    "state_contents",
    [
        "{broken",
        "[]",
        '{"custom.html": "bad-hash"}',
        '{"custom.html": []}',
        '{"custom.html": ["bad-hash"]}',
    ],
)
def test_invalid_report_state_preserves_reports_and_explains_recovery(
    project: Path, state_contents: str
) -> None:
    args = ["what-changed", "last-read", "--project", str(project)]
    result = CliRunner().invoke(workspace, args)
    assert result.exit_code == 0, result.output
    report = project / "_site/what-changed.html"
    previous = report.read_bytes()
    state = project / workspace_module.DIFF_STATE
    state.write_text(state_contents)
    result = CliRunner().invoke(workspace, args)
    assert result.exit_code != 0
    assert "Invalid comparison report state" in result.output
    assert "remove the generated comparison reports" in result.output
    assert report.read_bytes() == previous
    assert state.read_text() == state_contents
    assert "Wrote " not in result.stdout


def test_missing_baseline_layout_does_not_fetch_script(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = project / "new-workspace"
    nested.mkdir()
    (project / "index.qmd").rename(nested / "index.qmd")
    (project / "scripts").rename(nested / "scripts")
    monkeypatch.setattr(
        workspace_module, "diff_script", lambda *_: pytest.fail("unexpected sync")
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(nested)]
    )
    assert result.exit_code != 0
    assert "Project directory does not exist for last-read:" in result.output
    assert "new-workspace" in result.output
    assert "Rendering " not in result.output
    assert (
        len(
            subprocess.check_output(
                ["git", "-C", str(project), "worktree", "list"], text=True
            ).splitlines()
        )
        == 1
    )


def test_internal_sync_status_uses_stderr(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "scripts/what-changed.py").unlink()
    workflow = project / ".github/workflows/docs.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n  docs:\n"
        "    uses: allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@main\n"
    )
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
        data = (ASSETS / "what-changed.py").read_bytes()
        member = tarfile.TarInfo(
            "source/" + workspace_module.ASSET_DIR + "what-changed.py"
        )
        member.size = len(data)
        bundle.addfile(member, io.BytesIO(data))
    monkeypatch.setattr(
        workspace_module, "load_asset", lambda *_: (b"# rules", archive.getvalue())
    )
    args = ["what-changed", "last-read", "--project", str(project)]
    for status in ("Loaded workspace.mk", "workspace.mk already cached"):
        result = CliRunner().invoke(workspace, args)
        assert result.exit_code == 0, result.output
        assert status in result.stderr
        assert status not in result.stdout
        assert "Wrote " in result.stdout


@pytest.mark.parametrize("directory", [".", "research workspace/docs"])
def test_template_with_real_quarto(tmp_path: Path, directory: str) -> None:
    source = os.environ.get("ASTA_TEST_WORKSPACE_TEMPLATE")
    if not source:
        pytest.skip("Set ASTA_TEST_WORKSPACE_TEMPLATE to a workspace-template checkout")
    assert shutil.which("make") and shutil.which("quarto")
    repository = tmp_path / "project"
    project = repository / directory
    project.parent.mkdir(parents=True, exist_ok=True)
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
    git(repository, "init", "-q")
    git(project, "add", *files)
    git(repository, "commit", "-qm", "template baseline")
    git(repository, "tag", "last-read")
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
