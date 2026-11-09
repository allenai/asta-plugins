"""`asta workspace what-changed` compares a git ref's rendered site with the working tree."""

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.client import HTTPConnection
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest
import yaml
from click.testing import CliRunner

from asta.commands import workspace as workspace_module
from asta.commands.workspace import workspace

ASSETS = Path(__file__).parent.parent / "plugins/asta-tools/skills/workspace/assets"

# Stands in for `make render` -> `quarto render`: wraps index.qmd in the
# <main> Quarto emits, so the test needs neither make nor Quarto.
FAKE_MAKE = """#!/usr/bin/env python3
import pathlib, sys
assert sys.argv[1:6] == ["-o", "workspace-assets", "-o", "workspace-viewers", "render"], sys.argv
assert all(arg.startswith("ASTA_WORKSPACE_RENDER_") for arg in sys.argv[6:]), sys.argv
paras = "".join(f"<p>{line}</p>" for line in open("index.qmd").read().splitlines())
pathlib.Path("_site").mkdir(exist_ok=True)
pathlib.Path("_site/index.html").write_text(
    f"<html><head><title>Report</title></head><body><main>{paras}</main></body></html>"
)
"""

# Stands in for `quarto`: records each render's directory, arguments and page.
FAKE_QUARTO = """#!/usr/bin/env python3
import os, sys
if sys.argv[1] != "render":
    sys.exit(1)
with open(os.environ["ORDER_LOG"], "a") as log:
    log.write(
        "quarto\\t" + os.getcwd() + "\\t" + " ".join(sys.argv[1:]) + "\\t"
        + str(os.path.isfile(sys.argv[2])) + "\\t"
        + os.environ["XDG_CACHE_HOME"] + "\\n"
    )
"""

PRIME_QUARTO_SASS_CACHE = workspace_module.prime_quarto_sass_cache


def git(project: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=project,
        check=True,
        capture_output=True,
    )


def assert_single_worktree(project: Path) -> None:
    worktrees = subprocess.check_output(
        ["git", "-C", str(project), "worktree", "list", "--porcelain"], text=True
    )
    assert sum(line.startswith("worktree ") for line in worktrees.splitlines()) == 1


@pytest.fixture
def project(
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    monkeypatch.setattr(
        workspace_module,
        "_comparison_script",
        lambda: next(
            (
                tmp_path
                if tmp_path.exists()
                else tmp_path.with_name(tmp_path.name + " workspace ")
            ).rglob("scripts/what-changed.py")
        ),
    )
    monkeypatch.setattr(
        workspace_module,
        "_comparison_python",
        lambda decks: ([sys.executable], os.environ.copy()),
    )
    # Quarto's real cache is not touched by the tests that stub the renders.
    monkeypatch.setattr(workspace_module, "prime_quarto_sass_cache", lambda _: None)
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
    assert (
        "Overlaying " in result.stderr
        and "changed/untracked render inputs" in result.stderr
    )
    assert "Overlaying " not in result.stdout
    page = (project / ".asta/cache/what-changed/what-changed.html").read_text()
    assert "Changes since last-read" in page
    assert "<ins" in page and "newly drafted paragraph" in page
    assert_single_worktree(project)


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
    assert_single_worktree(project)


@pytest.mark.parametrize("side", ["baseline", "working"])
@pytest.mark.parametrize("outcome", ["success", "render", "clone"])
def test_private_clones_leave_source_git_untouched(project, monkeypatch, side, outcome):
    original = workspace_module._git
    clones = []
    registration = project / ".git/worktrees"

    def observe(directory, *args):
        assert args[:2] != ("worktree", "add")
        result = original(directory, *args)
        if args[0] == "clone":
            clone = Path(args[-1])
            clones.append(clone)
            assert (clone / ".git").is_dir()
            if clone.name == side and outcome == "clone":
                return subprocess.CompletedProcess(args, 1, stderr="Clone failed")
        return result

    monkeypatch.setattr(workspace_module, "_git", observe)
    if outcome == "render":
        make = Path(shutil.which("make"))
        make.write_text(
            "#!/usr/bin/env python3\nimport pathlib\n"
            f"if pathlib.Path.cwd().name == {side!r}: raise SystemExit(2)\n" + FAKE_MAKE
        )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == (0 if outcome == "success" else 1), result.output
    assert clones and all(not clone.parent.exists() for clone in clones)
    assert not registration.exists()
    assert_single_worktree(project)


def test_subdirectory_uses_git_prefix_with_repository_alias(project: Path, monkeypatch):
    nested = project / "site"
    nested.mkdir()
    (project / "index.qmd").rename(nested / "index.qmd")
    (project / "scripts").rename(nested / "scripts")
    git(project, "add", ".")
    git(project, "commit", "-qm", "nested workspace")
    git(project, "tag", "-f", "last-read")
    (nested / "index.qmd").write_text("An edit through an aliased repository.\n")
    cache = nested / ".asta/cache"
    cache.mkdir(parents=True)
    (cache / "workspace.mk").write_text("Cached build rules")
    original = workspace_module._git
    alias = project.with_name(project.name + "-alias")
    alias.symlink_to(project, target_is_directory=True)

    def alias_toplevel(directory, *args):
        result = original(directory, *args)
        if args == ("rev-parse", "--show-toplevel"):
            result.stdout = str(alias) + "\n"
        return result

    monkeypatch.setattr(workspace_module, "_git", alias_toplevel)
    original_render = workspace_module.render_site

    def render(directory, label, pages=None):
        if label == "the working tree":
            assert (
                directory / ".asta/cache/workspace.mk"
            ).read_text() == "Cached build rules"
        return original_render(directory, label, pages)

    monkeypatch.setattr(workspace_module, "render_site", render)
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(nested)]
    )
    assert result.exit_code == 0, result.output
    page = (nested / workspace_module.COMPARISON_DIR / "what-changed.html").read_text()
    assert "<ins" in page and "aliased repository" in page
    assert_single_worktree(project)


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


@pytest.mark.parametrize("version", ["2.29.9", "2.24.4", "1.9.5"])
def test_old_git_has_actionable_error(project: Path, monkeypatch, version):
    original = workspace_module._git

    def older_git(directory, *args):
        assert args[:2] != ("worktree", "add")
        if args == ("--version",):
            return subprocess.CompletedProcess(
                args, 0, stdout=f"git version {version}\n"
            )
        return original(directory, *args)

    monkeypatch.setattr(workspace_module, "_git", older_git)
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 1
    assert "Git 2.30 or newer is required" in result.output
    assert version in result.output
    assert "Unknown git ref" not in result.output
    assert_single_worktree(project)


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
    assert_single_worktree(project)


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
    assert_single_worktree(project)


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
    assert_single_worktree(project)


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
    assert (
        "what-changed-snapshot/what-changed.html"
        in (project / "_site/what-changed.html").read_text()
    )
    assert sorted(p.name for p in (project / "_site").iterdir()) == [
        "index.html",
        "what-changed-snapshot",
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


def test_working_copy_overlays_only_changes(project: Path, tmp_path: Path, monkeypatch):
    """HEAD supplies unchanged files; copying is limited to the working edit."""
    import shutil

    unchanged = (project / "scripts/what-changed.py").read_bytes()
    (project / "index.qmd").write_text("Changed page")
    copied = []
    original = shutil.copy2

    def record(source, target, **kwargs):
        copied.append(Path(source).relative_to(project).as_posix())
        return original(source, target, **kwargs)

    monkeypatch.setattr(workspace_module.shutil, "copy2", record)
    destination = workspace_module.working_copy(project, "", tmp_path / "overlay")
    assert (destination / "scripts/what-changed.py").read_bytes() == unchanged
    assert (destination / "index.qmd").read_text() == "Changed page"
    assert copied == ["index.qmd"]


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
        copied = workspace_module.working_copy(project, "", destination)
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
        copied = workspace_module.working_copy(project, "", destination)
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


def test_both_renders_are_parallel_private_clones(project, monkeypatch):
    original = workspace_module.render_site
    barrier = threading.Barrier(2, timeout=10)

    def render(directory, label, pages=None):
        assert (directory / ".git").is_dir()
        barrier.wait()
        return original(directory, label, pages)

    monkeypatch.setattr(workspace_module, "render_site", render)
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    assert_single_worktree(project)


def test_sass_cache_is_created_once_before_the_two_renders(
    project, monkeypatch, tmp_path_factory
):
    monkeypatch.setattr(
        workspace_module, "prime_quarto_sass_cache", PRIME_QUARTO_SASS_CACHE
    )
    log = tmp_path_factory.mktemp("order-log") / "order.txt"
    shared = tmp_path_factory.mktemp("user-cache")
    monkeypatch.setenv("ORDER_LOG", str(log))
    monkeypatch.setenv("XDG_CACHE_HOME", str(shared))
    quarto_dir = tmp_path_factory.mktemp("quarto-bin")
    (quarto_dir / "quarto").write_text(FAKE_QUARTO)
    (quarto_dir / "quarto").chmod(0o755)
    monkeypatch.setenv("PATH", f"{quarto_dir}{os.pathsep}{os.environ['PATH']}")
    make = Path(shutil.which("make"))
    make.write_text(
        make.read_text()
        + "import os\n"
        + "with open(os.environ['ORDER_LOG'], 'a') as log:\n"
        + "    log.write('make\\t' + os.getcwd() + '\\t\\t\\t' "
        + "+ os.environ['XDG_CACHE_HOME'] + '\\n')\n"
    )
    (project / "index.qmd").write_text("The baseline finding holds.\nAn edit.\n")
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    steps = [line.split("\t") for line in log.read_text().splitlines()]
    assert [step[0] for step in steps] == ["quarto", "make", "make"], steps
    _, directory, arguments, page_existed, _ = steps[0]
    assert arguments == "render sass-cache.md --to html --quiet"
    assert page_existed == "True"
    assert not Path(directory).resolve().is_relative_to(project.resolve())
    assert not any(
        Path(directory).resolve() in Path(step[1]).resolve().parents
        or Path(step[1]).resolve() in Path(directory).resolve().parents
        for step in steps[1:]
    )
    # No environment variable is changed for any of them.
    assert {step[4] for step in steps} == {str(shared)}


@pytest.mark.parametrize("intent_to_add", [False, True])
def test_render_uses_staged_page_list(project: Path, intent_to_add: bool) -> None:
    (project / "removed.qmd").write_text("The removed finding.")
    git(project, "add", "removed.qmd")
    git(project, "commit", "-qm", "add removed page")
    git(project, "tag", "-f", "last-read")
    (project / "added.qmd").write_text("The newly staged finding.")
    git(project, "add", *(["-N"] if intent_to_add else []), "added.qmd")
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


@pytest.mark.parametrize("phase", ["clone", "ls-files", "update-index"])
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
        copying = args[0] == "clone" and Path(args[-1]).name == "working"
        if copying:
            temporary = Path(args[-1]).parent
        if (
            args[0] == phase
            and (copying or phase != "clone")
            and (phase != "ls-files" or "--stage" in args)
        ):
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
    assert_single_worktree(project)


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
        assert result.stderr.count(f"build-diagnostic-{i:03d}") == 2


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
        "[::1]",
        "[::1]:12345",
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


@pytest.mark.parametrize("phase", ["render"])
@pytest.mark.skipif(os.name != "posix", reason="POSIX termination")
def test_termination_cleans_comparison_and_children(project: Path, phase: str) -> None:
    owned = project / workspace_module.COMPARISON_DIR
    owned.mkdir(parents=True)
    (owned / "what-changed.html").write_text("Previous report")
    # Both sides render at once, so each blocked child records its own pid.
    ready = project / "child-ready"
    ready.mkdir()
    child_code = (
        "import os, pathlib, time\n"
        f"ready = pathlib.Path({str(ready)!r})\n"
        "partial = ready / f'{os.getpid()}.partial'\n"
        "partial.write_text(str(os.getpid()))\n"
        "os.replace(partial, ready / str(os.getpid()))\n"
        "time.sleep(60)\n"
    )

    def children() -> list[int]:
        return [int(path.name) for path in ready.iterdir() if path.name.isdigit()]

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
    try:
        deadline = time.monotonic() + 10
        while not children() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert children(), "Comparison never reached the blocked child"
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 128 + signal.SIGTERM, (stdout, stderr)
        assert (owned / "what-changed.html").read_text() == "Previous report"
        assert not list(owned.parent.glob(".what-changed-*"))
        assert_single_worktree(project)
        for child in children():
            with pytest.raises(ProcessLookupError):
                os.kill(child, 0)
    finally:
        for child in children():
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
        if args[0] == "clone":
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
    assert_single_worktree(project)


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


# Records the arguments and writes one slide image, as deck rendering would.
DECK_DIFF = """import pathlib, sys
args = sys.argv[1:]
option = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in args if "=" in a}
pathlib.Path(args[args.index("--out") + 1]).write_text(" ".join(args))
if "--render-decks" in option:
    images = pathlib.Path(option["--render-decks"])
    images.mkdir(parents=True)
    (images / "slide-1.png").write_bytes(b"png")
"""


@pytest.mark.parametrize("deck", [True, False])
def test_site_with_deck_renders_slides_beside_the_page(project: Path, deck) -> None:
    (project / "scripts/what-changed.py").write_text(DECK_DIFF)
    body = '<div class="reveal">Slides</div>' if deck else "Prose only"
    (project / "index.qmd").write_text(body + "\n")
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    owned = project / workspace_module.COMPARISON_DIR
    page = (owned / "what-changed.html").read_text()
    assert ("--render-decks-url=what-changed-decks" in page) is deck
    assert ("--render-decks=" in page) is deck
    assert (owned / "what-changed-decks/slide-1.png").is_file() is deck
    assert_single_worktree(project)


THEMED = (
    '<html><head><link href="site_libs/bootstrap/bootstrap.min.css" '
    'rel="stylesheet" id="quarto-bootstrap"></head><body>{}</body></html>'
)


REDIRECT = (
    "<html><head><title>Redirect to {0}</title>"
    '<meta http-equiv="refresh" content="0;url={0}"></head></html>'
)


@pytest.mark.parametrize("home_redirects", [False, True])
@pytest.mark.parametrize("preview", [None, "deck-only", "redirect", "unstyled", "site"])
def test_partial_render_keeps_site_theme_without_a_site_page(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    preview: str | None,
    home_redirects: bool,
) -> None:
    """A slide-only edit must still read like the site (no browser-default page)."""
    (project / "_metadata.yml").write_text("format: revealjs\n")
    (project / "slides.qmd").write_text("Slide one.\n")
    if home_redirects:
        # The home page only redirects, so the theme must come from another page.
        (project / "index.qmd").write_text(
            '<meta http-equiv="refresh" content="0;url=about.html">\n'
        )
        (project / "about.qmd").write_text("About.\n")
        git(project, "add", "index.qmd", "about.qmd")
    git(project, "add", "slides.qmd", "_metadata.yml")
    git(project, "commit", "-qm", "deck")
    git(project, "tag", "-f", "last-read")
    (project / "slides.qmd").write_text("Slide one, edited.\n")
    if preview:
        site = project / "_site"
        (site / "site_libs/bootstrap").mkdir(parents=True)
        (site / "site_libs/bootstrap/bootstrap.min.css").write_text("body{}")
        (site / "slides.html").write_text('<div class="reveal">Slide one.</div>')
        if preview == "site":
            (site / "index.html").write_text(THEMED.format("Home"))
        elif preview == "redirect":
            # A preview of only the deck: Quarto's redirect home, no stylesheets.
            (site / "index.html").write_text(REDIRECT.format("slides.html"))
        elif preview == "unstyled":
            # A page linking stylesheets this partial preview never built.
            (site / "notes.html").write_text(
                THEMED.format("Notes").replace("bootstrap.min", "missing")
            )
    rendered = []

    def render(directory, label, pages=None):
        rendered.append((label, pages))
        site = directory / "_site"
        site.mkdir()
        for name in pages or []:
            text = (directory / name).read_text()
            if "http-equiv" in text:
                (site / "index.html").write_text(REDIRECT.format("about.html"))
            elif name in ("index.qmd", "about.qmd", workspace_module.THEME_PAGE):
                (site / "site_libs/bootstrap").mkdir(parents=True, exist_ok=True)
                (site / "site_libs/bootstrap/bootstrap.min.css").write_text("b{}")
                html = Path(name).with_suffix(".html")
                (site / html).write_text(
                    THEMED.format("Home" if "dex" in name else text)
                )
            else:
                (site / Path(name).with_suffix(".html")).write_text(f"<p>{text}</p>")
        if not (site / "index.html").exists():
            # Quarto writes a redirect home page for a site rendered without one.
            (site / "index.html").write_text(
                "<html><head><title>Redirect to slides.html</title>"
                '<meta http-equiv="refresh" content="0;url=slides.html"></head></html>'
            )
        return site

    monkeypatch.setattr(workspace_module, "render_site", render)
    monkeypatch.setattr(
        workspace_module, "_changed_comparison_pages", lambda *_: ["slides.qmd"]
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    snapshot = project / workspace_module.COMPARISON_DIR
    page = (snapshot / "what-changed.html").read_text()
    assert 'href="site_libs/bootstrap/bootstrap.min.css"' in page
    assert (snapshot / "site_libs/bootstrap/bootstrap.min.css").is_file()
    assert "<ins" in page and "edited" in page
    # The home page only supplies the theme; it is never reported as new.
    assert "Home" not in page and ">index.html<" not in page
    assert "About" not in page and ">about.html<" not in page
    assert "Redirect" not in page and "removed</span>" not in page
    assert "unstyled" not in result.stderr
    # Only the tiny look page joins the deck, in the same build on both
    # sides; no project page (home, redirect or other) is rendered for it.
    expected = ["slides.qmd", workspace_module.THEME_PAGE]
    assert dict(rendered)["the working tree"] == expected
    assert dict(rendered)["last-read"] == expected


def test_look_page_joins_a_project_render_list(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project listing its pages in project.render still gets the look page."""
    (project / "_metadata.yml").write_text("format: revealjs\n")
    (project / "slides.qmd").write_text("Slide one.\n")
    config = "# kept\nproject:\n  type: website\n  render:\n    - slides.qmd\n"
    (project / "_quarto.yml").write_text(config)
    git(project, "add", "slides.qmd", "_metadata.yml", "_quarto.yml")
    git(project, "commit", "-qm", "deck")
    git(project, "tag", "-f", "last-read")
    (project / "slides.qmd").write_text("Slide one, edited.\n")
    rendered = []

    def inputs(directory):
        # As `quarto inspect` lists them: only the render list.
        listed = yaml.safe_load((directory / "_quarto.yml").read_text())
        return {(directory / n).resolve() for n in listed["project"]["render"]}

    def render(directory, label, pages=None):
        listed = yaml.safe_load((directory / "_quarto.yml").read_text())
        # Quarto refuses a page outside project.render with --output-dir.
        assert set(pages) <= set(listed["project"]["render"])
        rendered.append((label, pages))
        site = directory / "_site"
        site.mkdir()
        for name in pages:
            if name == workspace_module.THEME_PAGE:
                (site / "site_libs/bootstrap").mkdir(parents=True)
                (site / "site_libs/bootstrap/bootstrap.min.css").write_text("b{}")
                (site / Path(name).with_suffix(".html")).write_text(
                    THEMED.format("Look")
                )
            else:
                text = (directory / name).read_text()
                (site / Path(name).with_suffix(".html")).write_text(
                    f'<div class="reveal">{text}</div>'
                )
        return site

    monkeypatch.setattr(workspace_module, "render_site", render)
    monkeypatch.setattr(workspace_module, "_comparison_inputs", inputs)
    monkeypatch.setattr(
        workspace_module, "_changed_comparison_pages", lambda *_: ["slides.qmd"]
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    expected = ["slides.qmd", workspace_module.THEME_PAGE]
    assert dict(rendered) == {"the working tree": expected, "last-read": expected}
    snapshot = project / workspace_module.COMPARISON_DIR
    page = (snapshot / "what-changed.html").read_text()
    assert 'href="site_libs/bootstrap/bootstrap.min.css"' in page
    assert "unstyled" not in result.stderr
    assert (project / "_quarto.yml").read_text() == config


def test_changed_home_page_supplies_the_theme_beside_a_deck(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the home page itself changed, its rendered page themes the report."""
    (project / "_metadata.yml").write_text("format: revealjs\n")
    (project / "slides.qmd").write_text("Slide one.\n")
    (project / "index.qmd").write_text("Home.\n")
    git(project, "add", "slides.qmd", "index.qmd", "_metadata.yml")
    git(project, "commit", "-qm", "deck and home")
    git(project, "tag", "-f", "last-read")
    (project / "slides.qmd").write_text("Slide one, edited.\n")
    (project / "index.qmd").write_text("Home, edited.\n")
    rendered = []

    def render(directory, label, pages=None):
        rendered.append((label, pages))
        site = directory / "_site"
        site.mkdir()
        (site / "site_libs/bootstrap").mkdir(parents=True)
        (site / "site_libs/bootstrap/bootstrap.min.css").write_text("b{}")
        for name in pages or []:
            text = (directory / name).read_text()
            body = THEMED.format(text) if name == "index.qmd" else f"<p>{text}</p>"
            (site / Path(name).with_suffix(".html")).write_text(body)
        return site

    monkeypatch.setattr(workspace_module, "render_site", render)
    monkeypatch.setattr(
        workspace_module,
        "_changed_comparison_pages",
        lambda *_: ["slides.qmd", "index.qmd"],
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    snapshot = project / workspace_module.COMPARISON_DIR
    page = (snapshot / "what-changed.html").read_text()
    assert 'href="site_libs/bootstrap/bootstrap.min.css"' in page
    assert (snapshot / "site_libs/bootstrap/bootstrap.min.css").is_file()
    assert "<ins" in page and "Home" in page
    # Under a root deck format the home page isn't surely ordinary, so the
    # look page joins it; either supplies the theme.
    assert dict(rendered)["the working tree"] == [
        "slides.qmd",
        "index.qmd",
        workspace_module.THEME_PAGE,
    ]


def test_deck_only_edit_renders_the_theme_and_cleans_up(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """The temporary theme folder is removed with the comparison directory."""
    temporary = tmp_path_factory.mktemp("comparisons")
    monkeypatch.setattr(tempfile, "tempdir", str(temporary))
    (project / "_metadata.yml").write_text("format: revealjs\n")
    (project / "slides.qmd").write_text("Slide one.\n")
    (project / "index.qmd").write_text("Home.\n")
    git(project, "add", "slides.qmd", "index.qmd", "_metadata.yml")
    git(project, "commit", "-qm", "deck")
    git(project, "tag", "-f", "last-read")
    rendered = []

    def render(directory, label, pages=None):
        rendered.append((label, pages))
        site = directory / "_site"
        site.mkdir()
        for name in pages or []:
            text = (directory / name).read_text()
            if name in ("index.qmd", workspace_module.THEME_PAGE):
                (site / "site_libs/bootstrap").mkdir(parents=True, exist_ok=True)
                (site / "site_libs/bootstrap/bootstrap.min.css").write_text("b{}")
                (site / "index.html").write_text(THEMED.format("Home"))
            else:
                (site / Path(name).with_suffix(".html")).write_text(f"<p>{text}</p>")
        return site

    monkeypatch.setattr(workspace_module, "render_site", render)
    monkeypatch.setattr(
        workspace_module, "_changed_comparison_pages", lambda *_: ["slides.qmd"]
    )
    snapshot = project / workspace_module.COMPARISON_DIR
    for edit in ("first", "second"):
        rendered.clear()
        (project / "slides.qmd").write_text(f"Slide one, {edit}.\n")
        result = CliRunner().invoke(
            workspace, ["what-changed", "last-read", "--project", str(project)]
        )
        assert result.exit_code == 0, result.output
        assert "cleanup failed" not in result.stderr
        assert not list(temporary.glob("asta-what-changed-*"))
        page = (snapshot / "what-changed.html").read_text()
        assert 'href="site_libs/bootstrap/bootstrap.min.css"' in page
        assert edit in page and "Home" not in page
        # Nothing is kept: every run adds the one theme page to both builds.
        assert dict(rendered)["the working tree"] == [
            "slides.qmd",
            workspace_module.THEME_PAGE,
        ]
        assert dict(rendered)["last-read"] == [
            "slides.qmd",
            workspace_module.THEME_PAGE,
        ]
        assert (snapshot / "site_libs/bootstrap/bootstrap.min.css").is_file()
    assert not (project / ".asta/cache/what-changed-theme").exists()
    assert_single_worktree(project)


def test_timings_report_each_step(project: Path) -> None:
    (project / "index.qmd").write_text("A timed paragraph.\n")
    result = CliRunner().invoke(
        workspace,
        ["what-changed", "last-read", "--project", str(project), "--timings"],
    )
    assert result.exit_code == 0, result.output
    log = result.output[result.output.index("What changed timings:") :]
    for step in (
        "check out baseline clone",
        "find changed pages",
        "copy working tree",
        "render before and after (parallel)",
        "stage site copy",
        "compare pages and picture slides",
        "publish snapshot",
        "other",
        "total",
    ):
        assert re.search(rf"^  {re.escape(step)} +.*\d+\.\d\d s$", log, re.M), step


def test_no_timings_without_flag(project: Path) -> None:
    (project / "index.qmd").write_text("An untimed paragraph.\n")
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    assert "What changed timings:" not in result.output


def _fake_paper_scripts(project):
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "paper-discovery.py").write_text(
        "import json\n"
        'print(json.dumps({"papers": ["paper"], "removed": ["old"], "warnings": []}))\n'
    )
    (scripts / "paper-preview.sh").write_text(
        'out="_site/paper-previews/$2"; mkdir -p "$out"; printf %s "$1" > "$out/base"\n'
        'printf \'{"changed":true,"diff":true}\\n\' > "$out/preview.json"\n'
    )


def test_local_paper_diff_built_when_tex_is_available(tmp_path, monkeypatch):
    workspace = workspace_module
    project = tmp_path / "project"
    _fake_paper_scripts(project)
    site = project / "_site"
    site.mkdir()
    monkeypatch.setattr(workspace.shutil, "which", lambda name: f"/usr/bin/{name}")

    workspace._paper_previews(project, "abc123", site)

    previews = site / "paper-previews"
    assert json.loads((previews / "paper/preview.json").read_text())["diff"] is True
    assert (previews / "paper/base").read_text() == "abc123"
    assert json.loads((previews / "old/preview.json").read_text()) == {
        "changed": True,
        "removed": True,
    }


def test_working_tree_snapshot_moves_head_to_uncommitted_edit(tmp_path):
    workspace = workspace_module
    project = tmp_path / "project"
    project.mkdir()
    git = ["git", "-C", str(project), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    (project / "main.tex").write_text("old\n")
    subprocess.run([*git, "add", "main.tex"], check=True)
    subprocess.run([*git, "commit", "-qm", "base"], check=True)
    base = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    (project / "main.tex").write_text("new\n")
    (project / "intro.tex").write_text("added\n")

    assert workspace._commit_working_tree(project)

    changed = subprocess.check_output(
        [*git, "diff", "--name-only", base, "HEAD"], text=True
    ).split()
    assert sorted(changed) == ["intro.tex", "main.tex"]
    parent = subprocess.check_output([*git, "rev-parse", "HEAD^"], text=True)
    assert parent.strip() == base


def test_local_paper_diff_skipped_with_note_without_tex(tmp_path, monkeypatch, capsys):
    workspace = workspace_module
    project = tmp_path / "project"
    _fake_paper_scripts(project)
    site = project / "_site"
    site.mkdir()
    monkeypatch.setattr(workspace.shutil, "which", lambda name: None)

    workspace._paper_previews(project, "abc123", site)

    assert not (site / "paper-previews").exists()
    assert "paper diffs are skipped" in capsys.readouterr().err


def test_files_quarto_does_not_render_never_reach_the_render(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A README or notes file changed beside a page is dropped before rendering."""
    (project / "page.qmd").write_text("Page.\n")
    (project / "README.md").write_text("Readme.\n")
    git(project, "add", "page.qmd", "README.md")
    git(project, "commit", "-qm", "base")
    git(project, "tag", "-f", "last-read")
    (project / "page.qmd").write_text("Page, edited.\n")
    (project / "README.md").write_text("Readme, edited.\n")
    rendered = []

    def render(directory, label, pages=None):
        rendered.append((label, pages))
        assert pages is not None and "README.md" not in pages
        site = directory / "_site"
        site.mkdir(exist_ok=True)
        for name in pages:
            html = site / Path(name).with_suffix(".html")
            html.write_text(f"<p>{(directory / name).read_text()}</p>")
        return site

    def inputs(directory):
        # As `quarto inspect` reports it: README.md is not a project input.
        return {p.resolve() for p in directory.glob("*.qmd") if p.name != "README.md"}

    monkeypatch.setattr(workspace_module, "render_site", render)
    monkeypatch.setattr(workspace_module, "_comparison_inputs", inputs)
    monkeypatch.setattr(
        workspace_module,
        "_changed_comparison_pages",
        lambda *_: ["README.md", "page.qmd"],
    )
    result = CliRunner().invoke(
        workspace, ["what-changed", "last-read", "--project", str(project)]
    )
    assert result.exit_code == 0, result.output
    assert dict(rendered)["the working tree"] == ["page.qmd"]
    assert "README.md" not in dict(rendered)["last-read"]
    page = (project / workspace_module.COMPARISON_DIR / "what-changed.html").read_text()
    assert "edited" in page and "Readme" not in page


def test_quarto_rendered_keeps_pages_when_inspect_is_unavailable(tmp_path: Path):
    for name in ("page.qmd", "README.md"):
        (tmp_path / name).write_text("x\n")
    names = ["page.qmd", "README.md", "deleted.qmd"]
    rendered = workspace_module._quarto_rendered
    assert rendered(tmp_path, names, {(tmp_path / "page.qmd").resolve()}) == [
        "page.qmd"
    ]
    assert rendered(tmp_path, names, None) == ["page.qmd", "README.md"]


def test_copy_ignored_render_inputs_fills_fresh_copies(
    project: Path, tmp_path: Path
) -> None:
    """A scaffolded workspace's ignored make rules and extensions reach each copy."""
    (project / ".gitignore").write_text(
        "_extensions/asta-theme/\n_extensions/evidence/\n.asta/cache/\n.env*\n"
    )
    theme = project / "_extensions/asta-theme"
    theme.mkdir(parents=True)
    (theme / "light.scss").write_text("/* theme */")
    (theme / ".env").write_text("SECRET=1")
    (project / "_extensions/evidence").mkdir()
    (project / "_extensions/evidence/snippet.lua").write_text("-- filter")
    cache = project / ".asta/cache"
    (cache / "what-changed").mkdir(parents=True)
    (cache / "what-changed/what-changed.html").write_text("Old report")
    (cache / "workspace.mk").write_text("Cached rules")
    destination = tmp_path / "baseline"
    (destination / "_extensions/evidence").mkdir(parents=True)
    (destination / "_extensions/evidence/snippet.lua").write_text("-- tracked")
    workspace_module.copy_ignored_render_inputs(project, destination)
    assert (destination / ".asta/cache/workspace.mk").read_text() == "Cached rules"
    assert (destination / "_extensions/asta-theme/light.scss").exists()
    assert not (destination / "_extensions/asta-theme/.env").exists()
    assert not (destination / ".asta/cache/what-changed").exists()
    # A file the copy already has (tracked at its commit) is not overwritten.
    assert (destination / "_extensions/evidence/snippet.lua").read_text() == (
        "-- tracked"
    )


@pytest.mark.parametrize("source_kind", ["detached", "linked"])
def test_working_copy_matches_source_head_in_every_checkout(tmp_path, source_kind):
    source = tmp_path / "repository"
    source.mkdir()
    git(source, "init", "-b", "main")
    (source / "index.qmd").write_text("Base")
    git(source, "add", "index.qmd")
    git(source, "commit", "-m", "Base")
    git(source, "checkout", "-b", "feature")
    (source / "index.qmd").write_text("Feature")
    git(source, "add", "index.qmd")
    git(source, "commit", "-m", "Feature")
    if source_kind == "linked":
        linked = tmp_path / "linked"
        git(source, "worktree", "add", "--detach", str(linked), "HEAD")
        source = linked
    else:
        git(source, "checkout", "--detach")
    expected = workspace_module._git(source, "rev-parse", "HEAD").stdout.strip()
    destination = tmp_path / "copy"
    workspace_module.working_copy(source, "", destination)
    assert (
        workspace_module._git(destination, "rev-parse", "HEAD").stdout.strip()
        == expected
    )
    assert (destination / "index.qmd").read_text() == "Feature"
