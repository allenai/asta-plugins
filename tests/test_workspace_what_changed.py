"""`asta workspace what-changed` compares a git ref's rendered site with the working tree."""

import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import threading
import time
from http.client import HTTPConnection
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
    page = (project / ".asta/cache/what-changed/what-changed.html").read_text()
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
    report = (nested / ".asta/cache/what-changed/what-changed.html").read_text()
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


@pytest.mark.parametrize("phase", ["success", "render", "script", "checkout"])
def test_locked_baseline_remains_recoverable(
    project: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    original = workspace_module._git
    baseline = None

    def lock_baseline(directory, *args):
        nonlocal baseline
        result = original(directory, *args)
        if args[:2] == ("worktree", "add") and "--no-checkout" not in args:
            assert result.returncode == 0
            baseline = Path(args[3])
            git(project, "worktree", "lock", str(baseline))
            if phase == "checkout":
                return subprocess.CompletedProcess(
                    args, 1, stderr="Checkout failed after registration"
                )
        return result

    monkeypatch.setattr(workspace_module, "_git", lock_baseline)
    if phase == "render":
        Path(shutil.which("make")).write_text(
            "#!/usr/bin/env python3\nraise SystemExit(2)\n"
        )
    elif phase == "script":
        (project / "scripts/what-changed.py").write_text("raise SystemExit(2)\n")
    try:
        result = CliRunner().invoke(
            workspace, ["what-changed", "last-read", "--project", str(project)]
        )
        assert result.exit_code == (0 if phase == "success" else 1), result.output
        assert baseline is not None
        assert (
            f"Warning: baseline worktree cleanup failed for {baseline}" in result.output
        )
        assert baseline.is_dir()
        assert (baseline / "index.qmd").read_text() == "The baseline finding holds.\n"
        git(baseline, "status", "--porcelain")
        worktrees = subprocess.check_output(
            ["git", "-C", str(project), "worktree", "list", "--porcelain"], text=True
        )
        assert f"worktree {baseline}\n" in worktrees and "locked\n" in worktrees
        if phase == "success":
            assert (project / ".asta/cache/what-changed/what-changed.html").is_file()
        else:
            assert "Wrote " not in result.output
    finally:
        if baseline is not None:
            git(project, "worktree", "unlock", str(baseline))
            git(project, "worktree", "remove", "--force", str(baseline))
            if baseline.parent.exists():
                baseline.parent.rmdir()
    assert (
        len(
            subprocess.check_output(
                ["git", "-C", str(project), "worktree", "list"]
            ).splitlines()
        )
        == 1
    )


@pytest.mark.parametrize("outcome", ["success", "render-failure", "cleanup-failure"])
def test_comparison_preserves_unavailable_worktree(
    project: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    unrelated = project.with_name(project.name + "-unrelated")
    offline = project.with_name(project.name + "-offline")
    git(project, "worktree", "add", "--detach", str(unrelated), "HEAD")
    (unrelated / "local-notes.txt").write_text("Uncommitted research notes")
    registration = Path(
        (unrelated / ".git").read_text().removeprefix("gitdir: ").strip()
    )
    git(project, "config", "gc.worktreePruneExpire", "now")
    unrelated.rename(offline)
    if outcome == "render-failure":
        Path(shutil.which("make")).write_text(
            "#!/usr/bin/env python3\nraise SystemExit(2)\n"
        )
    elif outcome == "cleanup-failure":
        original = workspace_module._git

        def fail_removal(directory, *args):
            if args[:2] == ("worktree", "remove"):
                return subprocess.CompletedProcess(args, 1, stderr="worktree is locked")
            return original(directory, *args)

        monkeypatch.setattr(workspace_module, "_git", fail_removal)
    try:
        result = CliRunner().invoke(
            workspace, ["what-changed", "last-read", "--project", str(project)]
        )
        assert result.exit_code == (1 if outcome == "render-failure" else 0), (
            result.output
        )
        assert registration.is_dir()
        worktrees = subprocess.check_output(
            ["git", "-C", str(project), "worktree", "list", "--porcelain"], text=True
        )
        assert f"worktree {unrelated}\n" in worktrees
    finally:
        offline.rename(unrelated)
    git(unrelated, "status", "--porcelain")
    assert (unrelated / "local-notes.txt").read_text() == "Uncommitted research notes"


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
        "Changes since -last-read"
        in (project / ".asta/cache/what-changed/what-changed.html").read_text()
    )


def test_diff_failure_names_selected_script_and_exit_code(project: Path) -> None:
    script = project / "scripts/what-changed.py"
    script.write_text("import sys\nsys.exit(7)\n")
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert f"what-changed.py failed (exit 7): {script}" in result.output


def test_project_script_runs_in_project_directory(
    project: Path, tmp_path_factory, monkeypatch
) -> None:
    (project / "relative-input.txt").write_text("Project-specific report")
    (project / "scripts/what-changed.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[sys.argv.index('--out') + 1]).write_text(\n"
        "    Path('relative-input.txt').read_text())\n"
    )
    caller = tmp_path_factory.mktemp("caller")
    (caller / "relative-input.txt").write_text("Wrong caller's report")
    monkeypatch.chdir(caller)
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    assert (
        project / workspace_module.COMPARISON_DIR / "what-changed.html"
    ).read_text() == ("Project-specific report")


@pytest.mark.parametrize("previous", ["directory", "file", "symlink", "absent"])
def test_publish_failure_preserves_previous_comparison(
    project: Path, monkeypatch, previous: str
) -> None:
    owned = project / workspace_module.COMPARISON_DIR
    owned.parent.mkdir(parents=True)
    external = project / "external"
    external.mkdir()
    (external / "keep.html").write_text("External content")
    if previous == "directory":
        owned.mkdir()
        (owned / "what-changed.html").write_text("Previous comparison")
    elif previous == "file":
        owned.write_text("Previous file")
    elif previous == "symlink":
        owned.symlink_to(external, target_is_directory=True)
    original = Path.replace

    def fail_publication(path, destination):
        if path.name.startswith(".what-changed-") and not path.name.endswith(
            ".previous"
        ):
            raise OSError("Publication failed")
        return original(path, destination)

    monkeypatch.setattr(Path, "replace", fail_publication)
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "Wrote " not in result.output
    if previous == "directory":
        assert (owned / "what-changed.html").read_text() == "Previous comparison"
    elif previous == "file":
        assert owned.read_text() == "Previous file"
    elif previous == "symlink":
        assert owned.is_symlink() and owned.resolve() == external
    else:
        assert not owned.exists()
    assert "Could not publish the comparison: Publication failed" in result.output
    assert (external / "keep.html").read_text() == "External content"
    assert not list(owned.parent.glob(".what-changed-*"))
    assert (
        len(
            subprocess.check_output(
                ["git", "-C", str(project), "worktree", "list"]
            ).splitlines()
        )
        == 1
    )


def test_previous_comparison_cleanup_failure_does_not_hide_new_report(
    project: Path, monkeypatch
) -> None:
    args = ["what-changed", "last-read", "--project", str(project)]
    assert CliRunner().invoke(workspace, args).exit_code == 0
    owned = project / workspace_module.COMPARISON_DIR
    previous_report = (owned / "what-changed.html").read_text()
    (project / "index.qmd").write_text("The baseline finding holds.\nNew comparison.\n")
    original = shutil.rmtree

    def fail_previous_cleanup(path, *args, **kwargs):
        if Path(path).name.endswith(".previous"):
            raise PermissionError("Previous directory is read-only")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", fail_previous_cleanup)
    result = CliRunner().invoke(workspace, args)
    assert result.exit_code == 0, result.output
    assert "Warning: previous comparison cleanup failed:" in result.stderr
    assert "Wrote " in result.stdout
    assert "New comparison" in (owned / "what-changed.html").read_text()
    saved = list(owned.parent.glob(".what-changed-*.previous"))
    assert len(saved) == 1
    assert (saved[0] / "what-changed.html").read_text() == previous_report


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
    owned = project / workspace_module.COMPARISON_DIR
    if stale_output:
        owned.mkdir(parents=True)
        (owned / "what-changed.html").write_text("A previous report")
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "did not write nonempty HTML" in result.output
    assert "Wrote " not in result.output
    output = owned / "what-changed.html"
    if stale_output:
        assert output.read_text() == "A previous report"
    else:
        assert not owned.exists()
    assert not (project / "_site/what-changed.html").exists()
    assert not list(owned.parent.glob(".what-changed-*"))
    worktrees = subprocess.run(
        ["git", "worktree", "list"], cwd=project, capture_output=True, text=True
    ).stdout
    assert len(worktrees.strip().splitlines()) == 1


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
    subprocess.run(["make", "render"], cwd=project, check=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with workspace_module.preview_process(
        ["quarto", "preview", "--no-browser", "--port", str(port)],
        project,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    ) as live:
        try:
            deadline = time.monotonic() + 30
            while True:
                assert live.poll() is None, "Live Quarto preview exited"
                try:
                    with urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                        assert response.status == 200
                        break
                except (URLError, TimeoutError):
                    assert time.monotonic() < deadline, "Live preview never started"
                    time.sleep(0.1)
            live_page = (project / "_site/index.html").read_bytes()
            for _ in range(2):
                result = CliRunner().invoke(
                    workspace, ["what-changed", "last-read", "--project", str(project)]
                )
                assert result.exit_code == 0, result.output
                report = (
                    project / ".asta/cache/what-changed/what-changed.html"
                ).read_text()
                assert re.search(r"<ins\b[^>]*>[^<]*newly drafted paragraph", report)
                assert "what-changed/what-changed.html" in result.stdout
                assert 'href="#what-changed-html"' not in report
                assert live.poll() is None
                assert (project / "_site/index.html").read_bytes() == live_page
        finally:
            workspace_module.stop_preview(live, signal.SIGTERM)
    manifest = json.loads((project / ".asta/cache/workspace.json").read_text())
    assert manifest["ref"] == ref
    assert "what-changed.py" in manifest["scripts"]


def test_site_files_are_never_modified(project: Path) -> None:
    # A project page with the report's name stays as rendered in _site/.
    Path(shutil.which("make")).write_text(
        FAKE_MAKE + "pathlib.Path('_site/what-changed.html').write_text('Own page')\n"
    )
    (project / "index.qmd").write_text(
        "The baseline finding holds.\nA newly drafted paragraph.\n"
    )
    (project / "_site").mkdir()
    (project / "_site/index.html").write_text("Live preview")
    (project / "_site/what-changed.html").write_text("Own page")
    args = ["what-changed", "last-read", "--project", str(project)]
    result = CliRunner().invoke(workspace, args)
    assert result.exit_code == 0, result.output
    assert (project / "_site/index.html").read_text() == "Live preview"
    assert (project / "_site/what-changed.html").read_text() == "Own page"
    assert sorted(p.name for p in (project / "_site").iterdir()) == [
        "index.html",
        "what-changed.html",
    ]
    owned = project / workspace_module.COMPARISON_DIR
    report = (owned / "what-changed.html").read_text()
    assert "newly drafted paragraph" in report
    # The page's relative links resolve against the site copy beside it.
    assert (owned / "index.html").is_file()
    assert "file://" not in result.stdout
    assert "asta workspace preview --what-changed" in result.stdout
    assert "http://localhost:4849/what-changed.html" in result.stdout


def test_live_preview_rebuild_cannot_change_diff_input(project: Path) -> None:
    (project / "index.qmd").write_text("A newly drafted paragraph.\n")
    script = project / "scripts/what-changed.py"
    # A live-preview rebuild between rendering and diffing used to replace --new.
    script.write_text(
        "from pathlib import Path\n"
        "Path('_site').mkdir(exist_ok=True)\n"
        "Path('_site/index.html').write_text('<main>Live preview rebuild</main>')\n"
        "exec(compile(" + repr(script.read_text()) + ", __file__, 'exec'))\n"
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    owned = project / workspace_module.COMPARISON_DIR
    assert "<ins>newly</ins>" in (owned / "what-changed.html").read_text()
    assert "Live preview rebuild" not in (owned / "what-changed.html").read_text()
    assert "newly drafted paragraph" in (owned / "index.html").read_text()


def test_working_copy_preserves_spaces_in_repository_path(project: Path) -> None:
    renamed = project.with_name(project.name + " workspace ")
    project.rename(renamed)
    (renamed / "index.qmd").write_text("A newly drafted paragraph.\n")
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(renamed)]
    )
    assert result.exit_code == 0, result.output
    assert (
        "newly drafted paragraph"
        in (renamed / workspace_module.COMPARISON_DIR / "index.html").read_text()
    )


@pytest.mark.parametrize("linked_worktree", [False, True])
def test_working_copy_keeps_render_inputs_and_git_index(
    project: Path, tmp_path_factory, linked_worktree: bool
) -> None:
    if linked_worktree:
        linked = tmp_path_factory.mktemp("linked") / "project"
        git(project, "worktree", "add", "--detach", str(linked), "HEAD")
        project = linked
    try:
        (project / ".gitignore").write_text("_site/\n.asta/cache/\nlocal-data/\n")
        (project / "local-data").mkdir()
        (project / "local-data/input.txt").write_text("Ignored data")
        (project / ".env").write_text("SECRET=1")
        (project / "notes").mkdir()
        (project / "notes/.env.local").write_text("SECRET=2")
        (project / "untracked dir").mkdir()
        (project / "untracked dir/new.qmd").write_text("New page")
        (project / "untracked.txt").write_text("Untracked input")
        (project / "index.qmd").write_text("Edited working content")
        (project / "scripts/what-changed.py").unlink()
        (project / "_site").mkdir()
        (project / "_site/index.html").write_text("Live output")
        cache = project / ".asta/cache"
        (cache / "what-changed").mkdir(parents=True)
        (cache / "what-changed/what-changed.html").write_text("Old report")
        (cache / "workspace.mk").write_text("Cached rules")
        (cache / ".what-changed-old.previous").mkdir()
        destination = tmp_path_factory.mktemp("snapshot") / "working"
        copied = workspace_module.working_copy(project, project, destination)
        assert not (copied / "local-data").exists()
        assert not (copied / ".env").exists()
        assert not (copied / "notes/.env.local").exists()
        assert (copied / "untracked dir/new.qmd").read_text() == "New page"
        assert (copied / "untracked.txt").read_text() == "Untracked input"
        assert (copied / "index.qmd").read_text() == "Edited working content"
        assert not (copied / "scripts/what-changed.py").exists()
        assert not (copied / "_site").exists()
        assert not (copied / ".asta/cache/what-changed").exists()
        assert not (copied / ".asta/cache/.what-changed-old.previous").exists()
        assert (copied / ".asta/cache/workspace.mk").read_text() == "Cached rules"
        tracked = subprocess.check_output(
            ["git", "-C", str(copied), "ls-files"], text=True
        ).splitlines()
        assert "scripts/what-changed.py" in tracked and "index.qmd" in tracked
        git(copied, "add", "untracked.txt")
        original_tracked = subprocess.check_output(
            ["git", "-C", str(project), "ls-files"], text=True
        ).splitlines()
        assert "untracked.txt" not in original_tracked
    finally:
        if linked_worktree:
            git(project, "worktree", "remove", "--force", str(project))


@pytest.mark.parametrize("linked_worktree", [False, True])
@pytest.mark.parametrize("split_index", [False, True])
def test_working_copy_preserves_staged_changes(
    project: Path, tmp_path_factory, linked_worktree: bool, split_index: bool
) -> None:
    if linked_worktree:
        linked = tmp_path_factory.mktemp("linked") / "project"
        git(project, "worktree", "add", "--detach", str(linked), "HEAD")
        project = linked
    try:
        (project / "removed.qmd").write_text("Old page")
        git(project, "add", "removed.qmd")
        git(project, "commit", "-qm", "add old page")
        (project / "index.qmd").write_text("Staged content")
        (project / "staged page\tnew.qmd").write_text("Staged new page")
        git(project, "add", "index.qmd", "staged page\tnew.qmd")
        git(project, "rm", "--cached", "removed.qmd")
        (project / "index.qmd").write_text("Unstaged content")
        if split_index:
            git(project, "update-index", "--split-index")
        original_index = subprocess.check_output(
            ["git", "-C", str(project), "ls-files", "--stage", "-z"]
        )
        destination = tmp_path_factory.mktemp("snapshot") / "working"
        copied = workspace_module.working_copy(project, project, destination)
        assert (
            subprocess.check_output(
                ["git", "-C", str(copied), "ls-files", "--stage", "-z"]
            )
            == original_index
        )
        assert (
            subprocess.check_output(
                ["git", "-C", str(copied), "show", ":index.qmd"], text=True
            )
            == "Staged content"
        )
        assert (copied / "index.qmd").read_text() == "Unstaged content"
        assert (copied / "staged page\tnew.qmd").read_text() == "Staged new page"
        # A staged deletion can remain on disk as an untracked render input.
        assert (copied / "removed.qmd").read_text() == "Old page"
        git(copied, "add", "removed.qmd")
        assert (
            subprocess.check_output(
                ["git", "-C", str(project), "ls-files", "--stage", "-z"]
            )
            == original_index
        )
    finally:
        if linked_worktree:
            git(project, "worktree", "remove", "--force", str(project))


def test_both_renders_find_the_main_checkout(project: Path) -> None:
    # Renders that locate an ignored virtualenv via the main checkout, as
    # `git rev-parse --git-common-dir` scripts do, must work in both copies.
    (project / ".gitignore").write_text("_site/\n.asta/cache/\n.venv/\n")
    git(project, "commit", "-qam", "ignore venv")
    git(project, "tag", "-f", "last-read")
    (project / ".venv").mkdir()
    (project / ".venv/marker").write_text("main venv")
    make = Path(shutil.which("make"))
    make.write_text(
        make.read_text() + "import subprocess\n"
        "common = subprocess.check_output(\n"
        "    ['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],\n"
        "    text=True,\n"
        ").strip()\n"
        "assert (pathlib.Path(common).parent / '.venv/marker').is_file(), common\n"
    )
    (project / "index.qmd").write_text("A finding that uses the venv.\n")
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    assert (
        "uses the venv"
        in (project / workspace_module.COMPARISON_DIR / "what-changed.html").read_text()
    )
    worktrees = subprocess.check_output(
        ["git", "-C", str(project), "worktree", "list"]
    ).splitlines()
    assert len(worktrees) == 1


def test_render_uses_staged_page_list(project: Path) -> None:
    (project / "removed.qmd").write_text("The removed finding.")
    git(project, "add", "removed.qmd")
    git(project, "commit", "-qm", "add removed page")
    git(project, "tag", "-f", "last-read")
    (project / "added.qmd").write_text("The newly staged finding.")
    git(project, "add", "added.qmd")
    git(project, "rm", "removed.qmd")
    Path(shutil.which("make")).write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, subprocess\n"
        "files = subprocess.check_output(['git', 'ls-files', '-z'], text=True)\n"
        "pathlib.Path('_site').mkdir(exist_ok=True)\n"
        "for name in files.split('\\0'):\n"
        "    path = pathlib.Path(name)\n"
        "    if path.suffix == '.qmd':\n"
        "        page = '<main><p>' + path.read_text() + '</p></main>'\n"
        "        (pathlib.Path('_site') / path.with_suffix('.html')).write_text(page)\n"
    )
    original_index = subprocess.check_output(
        ["git", "-C", str(project), "ls-files", "--stage", "-z"]
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    report = (
        project / workspace_module.COMPARISON_DIR / "what-changed.html"
    ).read_text()
    assert "newly staged finding" in report
    assert "removed finding" in report
    assert (project / workspace_module.COMPARISON_DIR / "added.html").is_file()
    assert not (project / workspace_module.COMPARISON_DIR / "removed.html").exists()
    assert (
        subprocess.check_output(
            ["git", "-C", str(project), "ls-files", "--stage", "-z"]
        )
        == original_index
    )


@pytest.mark.parametrize("phase", ["worktree", "ls-files", "update-index"])
def test_failed_working_copy_preserves_report_and_cleans_up(
    project: Path, monkeypatch, phase: str
) -> None:
    owned = project / workspace_module.COMPARISON_DIR
    owned.mkdir(parents=True)
    (owned / "what-changed.html").write_text("Previous report")
    original = workspace_module._git
    temporary = None

    def fail_copy(directory, *args):
        nonlocal temporary
        copying = "--no-checkout" in args
        if copying:
            temporary = Path(args[-2]).parent
        if args[0] == phase and (copying or phase != "worktree"):
            return subprocess.CompletedProcess(args, 1, stderr="Copy setup failed")
        return original(directory, *args)

    original_run = subprocess.run

    def fail_index(command, *args, **kwargs):
        if phase == "update-index" and "update-index" in command:
            return subprocess.CompletedProcess(command, 1, stderr="Copy setup failed")
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(workspace_module, "_git", fail_copy)
    monkeypatch.setattr(subprocess, "run", fail_index)
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "Copy setup failed" in result.output
    assert (owned / "what-changed.html").read_text() == "Previous report"
    assert temporary is not None and not temporary.exists()
    assert (
        len(
            subprocess.check_output(
                ["git", "-C", str(project), "worktree", "list"]
            ).splitlines()
        )
        == 1
    )


def test_diff_script_diagnostics_go_to_stderr(project: Path) -> None:
    script = project / "scripts/what-changed.py"
    script.write_text(
        "print('Custom diff diagnostic')\nexec(compile("
        + repr(script.read_text())
        + ", __file__, 'exec'))\n"
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    assert "Custom diff diagnostic" in result.stderr
    assert "Custom diff diagnostic" not in result.stdout
    assert "Wrote " in result.stdout


def test_cached_diff_lookup_works_without_click_context(project: Path) -> None:
    (project / "scripts/what-changed.py").unlink()
    sha = "a" * 64
    cache = project / ".asta/cache"
    cached = cache / "scripts" / sha / "what-changed.py"
    cached.parent.mkdir(parents=True)
    shutil.copy(ASSETS / "what-changed.py", cached)
    (cache / "workspace.json").write_text(
        json.dumps({"archive_sha256": sha, "scripts": {"what-changed.py": "hash"}})
    )
    (project / "workspace.mk").write_text("# Project-owned rules\n")
    assert workspace_module.diff_script(project) == cached


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_comparison_server_accepts_symlinked_parent(
    tmp_path: Path, method: str
) -> None:
    actual = tmp_path / "actual"
    site = actual / "site"
    site.mkdir(parents=True)
    (site / "index.html").write_text("Comparison homepage")
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    server = workspace_module.comparison_server(alias / "site", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        response = urlopen(
            Request(f"http://127.0.0.1:{server.server_port}/", method=method)
        )
        assert response.status == 200
        if method == "GET":
            assert response.read() == b"Comparison homepage"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("parent", [".asta", ".asta/cache"])
def test_symlinked_cache_parent_is_not_written(
    project: Path, parent: str, monkeypatch
) -> None:
    external = project / "external"
    previous = external / (
        "cache/what-changed" if parent == ".asta" else "what-changed"
    )
    previous.mkdir(parents=True)
    (previous / "keep.html").write_text("Unrelated content")
    link = project / parent
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(
        workspace_module, "diff_script", lambda *_: pytest.fail("unexpected sync")
    )
    monkeypatch.setattr(
        workspace_module, "render_site", lambda *_: pytest.fail("unexpected render")
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "Workspace cache must not be a symlink" in result.output
    assert list(previous.iterdir()) == [previous / "keep.html"]
    assert (previous / "keep.html").read_text() == "Unrelated content"
    assert not (project / "_site").exists()


def test_preview_serves_the_page_and_later_runs(project: Path) -> None:
    args = ["what-changed", "last-read", "--project", str(project)]
    (project / "index.qmd").write_text("The baseline finding holds.\nFirst edit.\n")
    assert CliRunner().invoke(workspace, args).exit_code == 0
    owned = project / workspace_module.COMPARISON_DIR
    server = workspace_module.comparison_server(owned, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        assert "First edit" in urlopen(base + "what-changed.html").read().decode()
        assert urlopen(base + "index.html").status == 200
        # A rerun replaces the directory; the running server shows the new page.
        (project / "index.qmd").write_text(
            "The baseline finding holds.\nSecond edit.\n"
        )
        assert CliRunner().invoke(workspace, args).exit_code == 0
        assert "Second edit" in urlopen(base + "what-changed.html").read().decode()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_comparison_preview_blocks_external_symlinks(
    tmp_path: Path, method: str
) -> None:
    site = tmp_path / "cache/site"
    site.mkdir(parents=True)
    (site / "page.html").write_text("Site page")
    (site / "local-link.html").symlink_to("page.html")
    external = tmp_path / "private"
    external.mkdir()
    (external / "secret.txt").write_text("Private local data")
    (site / "secret.txt").symlink_to(external / "secret.txt")
    (site / "private").symlink_to(external, target_is_directory=True)
    (site / "indexed").mkdir()
    (site / "indexed/index.html").symlink_to(external / "secret.txt")
    (site / "loop").symlink_to("loop")
    server = workspace_module.comparison_server(site, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        assert urlopen(Request(base + "local-link.html", method=method)).status == 200
        for path in (
            "secret.txt",
            "private/",
            "private/secret.txt",
            "indexed/",
            "loop",
        ):
            with pytest.raises(HTTPError) as error:
                urlopen(Request(base + path, method=method))
            # Path.resolve handles loops differently across supported Python versions.
            assert error.value.code in ((403, 404) if path == "loop" else (403,))
            assert b"Private local data" not in error.value.read()
        # Replacing the site must not bypass the check in an already-running server.
        shutil.rmtree(site)
        site.symlink_to(external, target_is_directory=True)
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "secret.txt", method=method))
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_preview_what_changed_requires_a_page(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        workspace, ["preview", "--what-changed", "--project", str(tmp_path)]
    )
    assert result.exit_code != 0
    assert "asta workspace what-changed <ref>" in result.output


def test_preview_what_changed_uses_codespace_url(project: Path, monkeypatch) -> None:
    import socket

    owned = project / workspace_module.COMPARISON_DIR
    owned.mkdir(parents=True)
    (owned / "what-changed.html").write_text("page")
    monkeypatch.setenv("CODESPACE_NAME", "cs")
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    monkeypatch.setattr(workspace_module, "WHAT_CHANGED_PORT", blocker.getsockname()[1])
    try:
        result = CliRunner().invoke(
            workspace, ["preview", "--what-changed", "--project", str(project)]
        )
    finally:
        blocker.close()
    assert result.exit_code != 0
    port = workspace_module.WHAT_CHANGED_PORT
    assert f"https://cs-{port}.app.github.dev/what-changed.html" in result.output


def test_repeat_run_replaces_the_owned_directory(project: Path) -> None:
    owned = project / workspace_module.COMPARISON_DIR
    owned.mkdir(parents=True)
    (owned / "leftover.html").write_text("from an earlier run")
    args = ["what-changed", "last-read", "--project", str(project)]
    for _ in range(2):
        result = CliRunner().invoke(workspace, args)
        assert result.exit_code == 0, result.output
    assert not (owned / "leftover.html").exists()
    assert (owned / "what-changed.html").is_file()
    assert not list(owned.parent.glob(".what-changed-*"))


def test_symlinked_owned_directory_is_replaced_not_followed(
    project: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    external = tmp_path_factory.mktemp("external")
    (external / "keep.html").write_text("outside the project")
    owned = project / workspace_module.COMPARISON_DIR
    owned.parent.mkdir(parents=True)
    owned.symlink_to(external, target_is_directory=True)
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    assert not owned.is_symlink()
    assert (owned / "what-changed.html").is_file()
    assert sorted(p.name for p in external.iterdir()) == ["keep.html"]


def test_missing_project_reports_directory_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        workspace, ["what-changed", "HEAD", "--project", str(tmp_path / "missing")]
    )
    assert result.exit_code == 2
    assert "does not exist" in result.output
    assert "Not a git repository" not in result.output


@pytest.mark.parametrize("workflow", [None, "jobs:\n  docs:\n    uses: invalid\n"])
def test_sync_error_keeps_cause_and_diff_script_guidance(
    project: Path, workflow
) -> None:
    (project / "scripts/what-changed.py").unlink()
    if workflow is not None:
        path = project / ".github/workflows/docs.yml"
        path.parent.mkdir(parents=True)
        path.write_text(workflow)
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert ("Missing" if workflow is None else "Expected one") in result.output
    assert "docs.yml" in result.output
    assert "No what-changed.py for this project" in result.output
    assert "scripts/what-changed.py" in result.output
    assert "asta workspace sync --refresh" in result.output


def test_failed_render_does_not_repeat_streamed_log(project: Path) -> None:
    Path(shutil.which("make")).write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "for i in range(100):\n"
        "    print(f'build-diagnostic-{i:03d}', file=sys.stderr)\n"
        "sys.exit(2)\n"
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "'make render' failed for last-read" in result.output
    for i in range(100):
        assert result.stderr.count(f"build-diagnostic-{i:03d}") == 1


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("domain", [None, "app.github.dev", "forwarded.example"])
def test_comparison_preview_rejects_untrusted_hosts(
    tmp_path: Path, monkeypatch, method: str, domain: str | None
) -> None:
    if domain is None:
        monkeypatch.delenv("CODESPACE_NAME", raising=False)
    else:
        monkeypatch.setenv("CODESPACE_NAME", "test-space")
        monkeypatch.setenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", domain)
    (tmp_path / "what-changed.html").write_text("Private draft")
    server = workspace_module.comparison_server(tmp_path, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/what-changed.html"
    allowed = [
        "localhost",
        "127.0.0.1",
        f"localhost:{port}",
        f"127.0.0.1:{port}",
        "localhost:1",
        "127.0.0.1:1",
        "[::1]",
        "[::1]:12345",
    ]
    if domain is not None:
        allowed.append(f"test-space-{port}.{domain}")
    rejected = [
        "",
        "attacker.example",
        "localhost.attacker.example",
        "localhost:invalid",
        "localhost:65536",
        "localhost@attacker.example",
        "attacker@localhost",
        "localhost/path",
        "localhost?query",
        "localhost#fragment",
    ]
    if domain is None:
        rejected.append(f"test-space-{port}.app.github.dev")
    else:
        rejected.extend([f"test-space-{port}.{domain}:443", f"test-space-1.{domain}"])
    try:
        for host in allowed:
            with urlopen(
                Request(url, headers={"Host": host}, method=method)
            ) as response:
                assert response.status == 200
        for host in rejected:
            with pytest.raises(HTTPError) as error:
                urlopen(Request(url, headers={"Host": host}, method=method))
            assert error.value.code == 403
            assert b"Private draft" not in error.value.read()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_comparison_preview_has_no_directory_listing(
    tmp_path: Path, method: str
) -> None:
    (tmp_path / "what-changed.html").write_text("Comparison")
    (tmp_path / "empty").mkdir()
    (tmp_path / "private-name").symlink_to(tmp_path.parent / "outside")
    server = workspace_module.comparison_server(tmp_path, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        for path in ("", "empty/"):
            with pytest.raises(HTTPError) as error:
                urlopen(Request(base + path, method=method))
            assert error.value.code == 404
            assert b"private-name" not in error.value.read()
        (tmp_path / "index.html").write_text("Project homepage")
        assert urlopen(Request(base, method=method)).status == 200
    finally:
        server.shutdown()
        server.server_close()


def test_comparison_cache_stays_private_throughout_copy(
    project: Path, monkeypatch
) -> None:
    (project / "_site").mkdir(mode=0o755)
    (project / "_site").chmod(0o755)
    original = shutil.copystat
    checked = []

    def check_copy_permissions(source, destination, **kwargs):
        original(source, destination, **kwargs)
        path = Path(destination)
        for parent in (path, *path.parents):
            if parent.name.startswith(".what-changed-"):
                assert parent.stat().st_mode & 0o777 == 0o700
                checked.append(parent)

    monkeypatch.setattr(shutil, "copystat", check_copy_permissions)
    for _ in range(2):
        result = CliRunner().invoke(
            workspace, ["what-changed", "last-read", "--project", str(project)]
        )
        assert result.exit_code == 0, result.output
        assert (
            project / workspace_module.COMPARISON_DIR
        ).stat().st_mode & 0o777 == 0o700
    assert checked


@pytest.mark.parametrize("phase", ["render", "script"])
@pytest.mark.skipif(os.name != "posix", reason="POSIX termination")
def test_termination_cleans_comparison_and_children(project: Path, phase: str) -> None:
    owned = project / workspace_module.COMPARISON_DIR
    owned.mkdir(parents=True)
    (owned / "what-changed.html").write_text("Previous report")
    ready = project / "child-ready"
    child_code = (
        "import os, pathlib, time\n"
        f"pathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    if phase == "render":
        Path(shutil.which("make")).write_text("#!/usr/bin/env python3\n" + child_code)
    else:
        (project / "scripts/what-changed.py").write_text(child_code)
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(
            word in k.upper()
            for word in ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY")
        )
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "asta.cli",
            "workspace",
            "what-changed",
            "last-read",
            "--project",
            str(project),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child = None
    try:
        deadline = time.monotonic() + 10
        while (
            not ready.exists()
            and process.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert ready.exists(), "Comparison never reached the blocked child"
        child = int(ready.read_text())
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 128 + signal.SIGTERM, (stdout, stderr)
        assert (owned / "what-changed.html").read_text() == "Previous report"
        assert not list(owned.parent.glob(".what-changed-*"))
        assert (
            len(
                subprocess.check_output(
                    ["git", "-C", str(project), "worktree", "list"]
                ).splitlines()
            )
            == 1
        )
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
    finally:
        if child is not None:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.communicate()


def test_failed_checkout_removes_partial_registration(
    project: Path, monkeypatch
) -> None:
    original = workspace_module._git

    def failed_add(directory, *args):
        result = original(directory, *args)
        if args[:2] == ("worktree", "add"):
            assert result.returncode == 0
            return subprocess.CompletedProcess(
                args, 1, stderr="Checkout failed after registration"
            )
        return result

    monkeypatch.setattr(workspace_module, "_git", failed_add)
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "Checkout failed after registration" in result.output
    assert (
        len(
            subprocess.check_output(
                ["git", "-C", str(project), "worktree", "list"]
            ).splitlines()
        )
        == 1
    )


def test_cached_diff_script_rejects_redirected_version(
    project: Path, monkeypatch
) -> None:
    (project / "scripts/what-changed.py").unlink()
    cache = project / ".asta/cache"
    scripts = cache / "scripts"
    scripts.mkdir(parents=True)
    sha = "a" * 64
    external = project / "external-scripts"
    external.mkdir()
    (external / "what-changed.py").write_text(
        "raise RuntimeError('Redirected script ran')"
    )
    (scripts / sha).symlink_to(external, target_is_directory=True)
    (cache / "workspace.json").write_text(
        json.dumps({"archive_sha256": sha, "scripts": {"what-changed.py": "hash"}})
    )
    monkeypatch.setattr(
        workspace_module, "sync_workspace", lambda *args, **kwargs: None
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code != 0
    assert "No what-changed.py for this project" in result.output
    assert "Redirected script ran" not in result.output


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_comparison_preview_preserves_http_file_behavior(
    tmp_path: Path, method: str
) -> None:
    (tmp_path / "pages").mkdir()
    content = b"<html>Comparison page</html>"
    (tmp_path / "pages/index.html").write_bytes(content)
    # Internal symlinks remain useful for rendered assets.
    (tmp_path / "linked.html").symlink_to(tmp_path / "pages/index.html")
    server = workspace_module.comparison_server(tmp_path, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/"
    try:
        paths = (
            ("pages", "pages/", "linked.html")
            if method == "GET"
            else ("pages/", "linked.html")
        )
        for path in paths:
            with urlopen(Request(base + path, method=method)) as response:
                assert response.status == 200
                assert response.headers["Content-type"] == "text/html"
                assert int(response.headers["Content-Length"]) == len(content)
                assert response.read() == (content if method == "GET" else b"")
                modified = response.headers["Last-Modified"]
        with pytest.raises(HTTPError) as error:
            urlopen(
                Request(
                    base + "linked.html",
                    method=method,
                    headers={"If-Modified-Since": modified},
                )
            )
        assert error.value.code == 304
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "missing.html", method=method))
        assert error.value.code == 404
        connection = HTTPConnection("127.0.0.1", server.server_port)
        try:
            connection.request(method, "/pages?view=1")
            response = connection.getresponse()
            assert response.status == 301
            assert response.headers["Location"] == "/pages/?view=1"
        finally:
            connection.close()
    finally:
        server.shutdown()
        server.server_close()
