"""`make what-changed` writes a local What changed page into `_site/` before any PR."""

import html
import json
import os
import re
import shutil
import signal
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

ASSETS = Path(__file__).parent.parent / "plugins/asta-tools/skills/workspace/assets"

# Models the single positional input and project-relative output directory from
# Quarto's CLI contract; QUARTO_LOG records each individual invocation.
FAKE_QUARTO = """#!/usr/bin/env python3
import json, os, pathlib, re, sys, time
def input_pages(root):
    root = root.resolve()
    excluded = json.loads(os.environ.get("QUARTO_EXCLUDED_INPUTS", "{}"))
    excluded = excluded.get(str(root), excluded.get(root.name, []))
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")
        if p.is_file() and p.suffix in {".qmd", ".md", ".ipynb", ".Rmd"}
        and not any(part.startswith(("_", ".")) for part in p.relative_to(root).parts)
        and str(p.relative_to(root)) not in excluded)
args = sys.argv[1:]
if args[0] == "inspect":
    root = pathlib.Path(args[1])
    if os.environ.get("QUARTO_INSPECT_NEEDS_EXTENSION"):
        assert (root / "_extensions/evidence/version.txt").is_file(), "missing extension"
    if os.environ.get("QUARTO_INSPECT_EDITS_IGNORE") and root == pathlib.Path("."):
        ignore = root / ".gitignore"
        if "/.quarto/" not in ignore.read_text():
            ignore.write_text(ignore.read_text() + "/.quarto/\\n")
    config = root / "_quarto.yml"
    match = re.search(r"output-dir:\\s*([^\\s]+)", config.read_text())
    print(json.dumps({"config": {"project": {"output-dir": match[1] if match else "_site"}},
        "files": {"input": [str((root / p).resolve()) for p in input_pages(root)]}}))
    sys.exit(0)
assert args[0] == "render", sys.argv
output = pathlib.Path("_site")
if "--output-dir" in args:
    index = args.index("--output-dir")
    output = pathlib.Path(args[index + 1])
    args = args[:index]
pages = [arg for arg in args[1:] if arg != "--no-clean"]
assert len(pages) <= 1, sys.argv
assert not any(page.startswith("-") for page in pages), sys.argv
if pages == ["."]:
    pages = []
assert not output.is_absolute(), sys.argv
if os.environ.get("QUARTO_LOG"):
    with open(os.environ["QUARTO_LOG"], "a") as log:
        log.write(json.dumps({"cwd": os.getcwd(), "pages": pages}) + "\\n")
if output == pathlib.Path("_site") and os.environ.get("QUARTO_BLOCK_BASE_RENDER"):
    pathlib.Path(os.environ["QUARTO_BLOCK_BASE_RENDER"]).write_text(str(pathlib.Path.cwd()))
    time.sleep(60)
extension = pathlib.Path("_extensions/evidence/version.txt").read_text()
required = pathlib.Path("required-extension.txt")
if required.exists():
    extension += pathlib.Path("_extensions", required.read_text().strip(), "version.txt").read_text()
output.mkdir(parents=True, exist_ok=True)
for page in pages or input_pages(pathlib.Path()):
    paras = f"<p>{extension}</p>" + "".join(f"<p>{line}</p>" for line in open(page).read().splitlines())
    destination = output / pathlib.Path(page).with_suffix(".html")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        f"<html><head><title>Report</title></head><body><main>{paras}</main></body></html>"
    )
"""

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="needs make")


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def git(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project = tmp_path / "report"
    project.mkdir()
    shutil.copy(ASSETS / "workspace.mk", project / "workspace.mk")
    (project / "Makefile").write_text("include workspace.mk\n")
    (project / "scripts").mkdir()
    shutil.copy(ASSETS / "what-changed.py", project / "scripts/what-changed.py")
    (project / ".gitignore").write_text("_site/\n_extensions/\n.asta/cache/\n")
    (project / "index.qmd").write_text("The baseline finding holds.\n")
    (project / "_quarto.yml").write_text("project:\n  type: website\n")
    git(project, "init", "-q", "-b", "main")
    (project / "_extensions/evidence").mkdir(parents=True)
    (project / "_extensions/evidence/version.txt").write_text("Baseline extension.")
    git(
        project,
        "add",
        "Makefile",
        "workspace.mk",
        "scripts",
        ".gitignore",
        "index.qmd",
        "_quarto.yml",
    )
    git(project, "add", "-f", "_extensions/evidence/version.txt")
    git(project, "commit", "-qm", "first")
    git(project, "checkout", "-qb", "draft")
    return project


def make_env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "quarto").write_text(FAKE_QUARTO)
    (bin_dir / "quarto").chmod(0o755)
    temporary = tmp_path / "temporary"
    temporary.mkdir(exist_ok=True)
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "TMPDIR": str(temporary),
    }


def make(project: Path, tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["make", "what-changed", "ASTA_WORKSPACE_VIEWERS=0", *args],
        cwd=project,
        env=make_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_uncommitted_edit_is_shown_against_branch_base(
    project: Path, tmp_path: Path
) -> None:
    (project / "index.qmd").write_text(
        "The baseline finding holds.\nA committed branch paragraph.\n"
    )
    git(project, "add", "index.qmd")
    git(project, "commit", "-qm", "branch work")
    (project / "index.qmd").write_text(
        "The baseline finding holds.\nA committed branch paragraph.\nA newly drafted paragraph.\n"
    )

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    page = (project / "_site/what-changed.html").read_text()
    assert "newly drafted paragraph" in page
    assert "committed branch paragraph" in page
    assert (
        f"Changes since {git(project, 'rev-parse', '--short', 'main').strip()}" in page
    )
    assert "<ins" in page
    assert not (project / "_site/index.html").exists()
    assert "_site/what-changed.html" in result.stdout
    assert "/what-changed.html" in result.stdout
    assert git(project, "rev-parse", "main").strip() in result.stderr
    worktrees = git(project, "worktree", "list", "--porcelain")
    assert sum(line.startswith("worktree ") for line in worktrees.splitlines()) == 1


def test_explicit_base_and_missing_base(project: Path, tmp_path: Path) -> None:
    git(project, "tag", "last-read")
    git(project, "branch", "-qm", "main", "unconfigured-base")
    (project / "index.qmd").write_text("A revised finding.\n")
    result = make(project, tmp_path, "WHAT_CHANGED_BASE=last-read")
    assert result.returncode == 0, result.stderr
    page = (project / "_site/what-changed.html").read_text()
    # Word-level markup can separate "revised" from the unchanged "finding".
    assert "revised" in page and "<ins" in page

    result = make(project, tmp_path)
    assert result.returncode != 0
    assert "WHAT_CHANGED_BASE" in result.stderr


@pytest.mark.parametrize("branch", ["master", "trunk", "custom-default"])
def test_local_default_branch(project: Path, tmp_path: Path, branch: str) -> None:
    git(project, "branch", "-m", "main", branch)
    if branch == "custom-default":
        git(project, "config", "init.defaultBranch", branch)
    git(project, "commit", "--allow-empty", "-qm", "branch work")
    (project / "index.qmd").write_text(
        "The baseline finding holds.\nA newly drafted paragraph.\n"
    )

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    page = (project / "_site/what-changed.html").read_text()
    assert "newly drafted paragraph" in page
    assert (
        f"Changes since {git(project, 'rev-parse', '--short', branch).strip()}" in page
    )


@pytest.mark.parametrize("cached_head", [True, False])
def test_remote_default_branch(
    project: Path, tmp_path: Path, cached_head: bool
) -> None:
    git(project, "branch", "-m", "main", "published-default")
    remote = tmp_path / "remote.git"
    git(project, "clone", "--bare", str(project), str(remote))
    git(remote, "symbolic-ref", "HEAD", "refs/heads/published-default")
    git(project, "remote", "add", "origin", str(remote))
    git(project, "fetch", "-q", "origin")
    if cached_head:
        git(project, "remote", "set-head", "origin", "-a")
    else:
        git(project, "update-ref", "--no-deref", "-d", "refs/remotes/origin/HEAD")
    git(project, "branch", "-D", "published-default")
    (project / "index.qmd").write_text(
        "The baseline finding holds.\nA newly drafted paragraph.\n"
    )

    result = make(project, tmp_path)

    if not cached_head:
        assert result.returncode != 0
        assert "WHAT_CHANGED_BASE" in result.stderr
        result = make(project, tmp_path, "WHAT_CHANGED_BASE=origin/published-default")
    assert result.returncode == 0, result.stderr
    page = (project / "_site/what-changed.html").read_text()
    assert "newly drafted paragraph" in page
    expected = git(project, "rev-parse", "--short", "origin/published-default").strip()
    assert f"Changes since {expected}" in page


def test_base_uses_its_own_render_rules(project: Path, tmp_path: Path) -> None:
    with (project / "Makefile").open("a") as f:
        f.write(
            "render: prepare-report\nprepare-report:\n\t@test -f required-extension.txt || printf evidence > required-extension.txt\n"
        )
    git(project, "add", "Makefile")
    git(project, "commit", "-qm", "prepare render inputs")
    git(project, "branch", "-f", "main")

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    assert (
        "No rendered content changed"
        in (project / "_site/what-changed.html").read_text()
    )


def test_baseline_keeps_its_recorded_extension(project: Path, tmp_path: Path) -> None:
    (project / "_extensions/evidence/version.txt").write_text("Current extension.")

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    page = (project / "_site/what-changed.html").read_text()
    assert "Baseline" in page and "Current" in page
    assert "<ins" in page and "<del" in page


@pytest.mark.parametrize("uncached_current", [False, True])
def test_inspection_prepares_each_versions_ignored_extensions(
    project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    uncached_current: bool,
) -> None:
    git(project, "rm", "--cached", "_extensions/evidence/version.txt")
    with (project / "Makefile").open("a") as file:
        file.write(
            "workspace-assets:\n\t@mkdir -p _extensions/evidence\n"
            "\t@printf 'Baseline extension.' > _extensions/evidence/version.txt\n"
        )
    git(project, "add", "Makefile")
    git(project, "commit", "-qm", "install ignored assets using the recorded rule")
    git(project, "branch", "-f", "main")
    if uncached_current:
        shutil.rmtree(project / "_extensions")
    (project / "index.qmd").write_text("A newly drafted paragraph.\n")
    monkeypatch.setenv("QUARTO_INSPECT_NEEDS_EXTENSION", "1")

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "preparing base workspace assets" in result.stderr
    if uncached_current:
        assert "preparing current workspace assets" in result.stderr
    assert "only pages changed" in result.stderr
    assert "drafted" in (project / "_site/what-changed.html").read_text()
    assert not list((tmp_path / "temporary").iterdir())


@pytest.mark.parametrize("preexisting_ignore_edit", [False, True])
def test_inspection_ignore_edits_do_not_change_source_selection(
    project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preexisting_ignore_edit: bool,
) -> None:
    (project / "index.qmd").write_text("A newly drafted paragraph.\n")
    if preexisting_ignore_edit:
        with (project / ".gitignore").open("a") as file:
            file.write("user-cache/\n")
    monkeypatch.setenv("QUARTO_INSPECT_EDITS_IGNORE", "1")
    log = tmp_path / "quarto.log"
    monkeypatch.setenv("QUARTO_LOG", str(log))

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    assert ("only pages changed" in result.stderr) != preexisting_ignore_edit
    expected = [[], []] if preexisting_ignore_edit else [["index.qmd"], ["index.qmd"]]
    assert rendered_pages(log) == expected
    assert ".gitignore changed during the build" in result.stderr
    assert "/.quarto/" in (project / ".gitignore").read_text()
    if preexisting_ignore_edit:
        assert "user-cache/" in (project / ".gitignore").read_text()


def test_explicit_makefile_is_used_for_current_probes_and_render(
    project: Path, tmp_path: Path
) -> None:
    # The baseline uses its recorded default Makefile; current invocations must
    # respect the outer -f even if a different default Makefile is present.
    (project / "local.mk").write_text("include workspace.mk\n")
    (project / "Makefile").write_text("render:\n\t@exit 99\n")
    (project / "index.qmd").write_text("A newly drafted paragraph.\n")

    result = make(project, tmp_path, "-f", "local.mk")

    assert result.returncode == 0, result.stderr
    assert "drafted" in (project / "_site/what-changed.html").read_text()


def test_baseline_does_not_borrow_ignored_extension(
    project: Path, tmp_path: Path
) -> None:
    (project / "required-extension.txt").write_text("custom")
    git(project, "add", "required-extension.txt")
    git(project, "commit", "-qm", "require a custom extension")
    git(project, "branch", "-f", "main")
    (project / "_extensions/custom").mkdir()
    (project / "_extensions/custom/version.txt").write_text(
        "Current ignored extension."
    )

    result = make(project, tmp_path)

    assert result.returncode != 0
    assert "base render failed" in result.stderr
    assert not (project / "_site/what-changed.html").exists()
    worktrees = git(project, "worktree", "list", "--porcelain")
    assert sum(line.startswith("worktree ") for line in worktrees.splitlines()) == 1


def test_live_preview_output_is_not_rendered_over(
    project: Path, tmp_path: Path
) -> None:
    (project / "_site").mkdir()
    live = project / "_site/index.html"
    live.write_text("Live preview output must stay intact.")
    (project / "index.qmd").write_text("A newly drafted paragraph.\n")

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    assert live.read_text() == "Live preview output must stay intact."
    assert "drafted" in (project / "_site/what-changed.html").read_text()
    assert not list((tmp_path / "temporary").iterdir())
    assert not list((project / ".asta/cache").glob("what-changed.*"))


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("prints_override", [False, True])
def test_custom_current_render_cannot_overwrite_preview(
    project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    full: bool,
    prints_override: bool,
) -> None:
    with (project / "Makefile").open("a") as file:
        file.write("render:\n")
        if prints_override:
            file.write("\t@echo '$(ASTA_WORKSPACE_RENDER_OUTPUT)'\n")
        file.write("\tquarto render\n")
    # The current recipe can be committed or uncommitted; only its behaviour
    # matters. Committing keeps a page-only change eligible for the fast path.
    git(project, "commit", "-qam", "custom current recipe")
    git(project, "branch", "-f", "main")
    (project / "index.qmd").write_text("A revised finding.\n")
    site = project / "_site"
    site.mkdir()
    live = site / "index.html"
    live.write_text("Live preview must stay intact.")
    log = tmp_path / "quarto.log"
    monkeypatch.setenv("QUARTO_LOG", str(log))

    result = make(project, tmp_path, *(["WHAT_CHANGED_FULL=1"] if full else []))

    assert result.returncode != 0
    assert "must honour ASTA_WORKSPACE_RENDER_OUTPUT" in result.stderr
    assert live.read_text() == "Live preview must stay intact."
    assert not (site / "what-changed.html").exists()
    if not prints_override:
        assert not log.exists(), "reject an unsafe recipe before either render runs"
    else:
        assert all(
            row["cwd"] != str(project)
            for row in map(json.loads, log.read_text().splitlines())
        )
    assert not list((tmp_path / "temporary").iterdir())
    assert git(project, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_empty_current_render_does_not_report_every_page_deleted(
    project: Path, tmp_path: Path
) -> None:
    with (project / "Makefile").open("a") as file:
        file.write("render:\n\t@echo '$(ASTA_WORKSPACE_RENDER_OUTPUT)'\n")
    (project / "_site").mkdir()
    report = project / "_site/what-changed.html"
    report.write_text("Previous comparison.")

    result = make(project, tmp_path)

    assert result.returncode != 0
    assert "current render produced no HTML" in result.stderr
    assert report.read_text() == "Previous comparison."
    assert not list((tmp_path / "temporary").iterdir())
    assert not list((project / ".asta/cache").glob("what-changed.*"))


@pytest.mark.parametrize("failure", ["assets", "report"])
def test_failed_publication_restores_previous_assets_and_report(
    project: Path, tmp_path: Path, failure: str
) -> None:
    site = project / "_site"
    assets = site / "what-changed-assets"
    assets.mkdir(parents=True)
    (assets / "previous.css").write_text("Previous theme.")
    (site / "what-changed.html").write_text("Previous comparison.")
    (project / "index.qmd").write_text("A newly drafted paragraph.\n")
    env = make_env(tmp_path)
    wrapper = tmp_path / "bin/mv"
    real_mv = shutil.which("mv")
    assert real_mv
    wrapper.write_text(
        "#!/usr/bin/env python3\nimport os, sys\nargs = sys.argv[1:]\n"
        f"failure = {failure!r}\n"
        "if (failure == 'assets' and args[-2].endswith('/new') "
        "and args[-1] == '_site/what-changed-assets') or "
        "(failure == 'report' and args[-1] == '_site/what-changed.html'):\n"
        "    sys.exit(1)\n"
        f"os.execv({real_mv!r}, [{real_mv!r}, *args])\n"
    )
    wrapper.chmod(0o755)

    result = subprocess.run(
        ["make", "what-changed", "ASTA_WORKSPACE_VIEWERS=0"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert (assets / "previous.css").read_text() == "Previous theme."
    assert (site / "what-changed.html").read_text() == "Previous comparison."
    assert not list(site.glob(".what-changed-publish.*"))
    assert not list((tmp_path / "temporary").iterdir())
    assert not list((project / ".asta/cache").glob("what-changed.*"))
    assert git(project, "worktree", "list", "--porcelain").count("worktree ") == 1


@pytest.mark.parametrize("custom_at_base", [False, True])
def test_nonstandard_site_output_is_rejected_before_rendering(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, custom_at_base: bool
) -> None:
    config = project / "_quarto.yml"
    config.write_text("project:\n  type: website\n  output-dir: docs\n")
    if custom_at_base:
        git(project, "add", "_quarto.yml")
        git(project, "commit", "-qm", "custom baseline output")
        git(project, "branch", "-f", "main")
        config.write_text("project:\n  type: website\n  output-dir: _site\n")
    log = tmp_path / "quarto.log"
    monkeypatch.setenv("QUARTO_LOG", str(log))

    result = make(project, tmp_path)

    assert result.returncode != 0
    assert "requires project.output-dir=_site in both versions" in result.stderr
    assert "docs" in result.stderr
    assert not log.exists()
    assert not (project / "_site/what-changed.html").exists()
    assert not list((tmp_path / "temporary").iterdir())
    assert git(project, "worktree", "list", "--porcelain").count("worktree ") == 1


@pytest.mark.parametrize("output", ["_site/", "./_site"])
def test_equivalent_site_output_paths_are_allowed(
    project: Path, tmp_path: Path, output: str
) -> None:
    (project / "_quarto.yml").write_text(
        f"project:\n  type: website\n  output-dir: {output}\n"
    )
    git(project, "add", "_quarto.yml")
    git(project, "commit", "-qm", "equivalent site directory")
    git(project, "branch", "-f", "main")
    (project / "index.qmd").write_text("A newly drafted paragraph.\n")

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "drafted" in (project / "_site/what-changed.html").read_text()


def test_project_in_repository_subdirectory(project: Path, tmp_path: Path) -> None:
    nested = project / "research workspace/docs"
    nested.mkdir(parents=True)
    for name in (
        "Makefile",
        "workspace.mk",
        "scripts",
        "index.qmd",
        "_extensions",
        "_quarto.yml",
    ):
        git(project, "mv", name, str(nested.relative_to(project) / name))
    git(project, "commit", "-qm", "move report into a subdirectory")
    git(project, "branch", "-f", "main")
    (nested / "index.qmd").write_text("A newly drafted paragraph.\n")

    result = make(nested, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "only pages changed" in result.stderr
    assert "drafted" in (nested / "_site/what-changed.html").read_text()
    assert not list((tmp_path / "temporary").iterdir())
    assert not list((project / ".asta/cache").glob("what-changed.*"))


@pytest.mark.parametrize("ref", ["last'read", "-baseline", "last$(read)"])
def test_explicit_ref_is_literal(project: Path, tmp_path: Path, ref: str) -> None:
    git(project, "update-ref", f"refs/tags/{ref}", "HEAD")
    (project / "index.qmd").write_text("A newly drafted paragraph.\n")

    result = make(project, tmp_path, f"WHAT_CHANGED_BASE={ref}")

    assert result.returncode == 0, result.stderr
    assert "drafted" in (project / "_site/what-changed.html").read_text()


def test_local_branch_is_not_confused_with_tag(project: Path, tmp_path: Path) -> None:
    git(project, "commit", "--allow-empty", "-qm", "branch work")
    git(project, "tag", "main")
    result = make(project, tmp_path)
    assert result.returncode == 0, result.stderr
    expected = git(project, "rev-parse", "--short", "refs/heads/main").strip()
    assert (
        f"Changes since {expected}" in (project / "_site/what-changed.html").read_text()
    )


@pytest.mark.parametrize("missing_tracking_ref", [True, False])
def test_remote_failure_falls_back_to_local_default(
    project: Path, tmp_path: Path, missing_tracking_ref: bool
) -> None:
    git(project, "remote", "add", "origin", str(tmp_path / "missing.git"))
    if missing_tracking_ref:
        git(
            project,
            "symbolic-ref",
            "refs/remotes/origin/HEAD",
            "refs/remotes/origin/missing",
        )

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    expected = git(project, "rev-parse", "--short", "main").strip()
    assert (
        f"Changes since {expected}" in (project / "_site/what-changed.html").read_text()
    )


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_signal_interrupt_removes_baseline_worktree(
    project: Path, tmp_path: Path, signum: int
) -> None:
    marker = tmp_path / "render-started"
    env = {**make_env(tmp_path), "QUARTO_BLOCK_BASE_RENDER": str(marker)}
    process = subprocess.Popen(
        ["make", "what-changed", "ASTA_WORKSPACE_VIEWERS=0"],
        cwd=project,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while (
            not marker.exists()
            and process.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert marker.exists(), process.communicate(timeout=2)
        baseline_project = Path(marker.read_text())
        os.killpg(process.pid, signum)
        _, stderr = process.communicate(timeout=10)
        assert process.returncode != 0, stderr
        assert not baseline_project.exists()
        assert not list((tmp_path / "temporary").iterdir())
        assert not list((project / ".asta/cache").glob("what-changed.*"))
        worktrees = git(project, "worktree", "list", "--porcelain")
        assert sum(line.startswith("worktree ") for line in worktrees.splitlines()) == 1
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)


def test_base_lookup_never_contacts_remote(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ssh = tmp_path / "fake-ssh"
    log = tmp_path / "ssh.json"
    ssh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['SSH_TEST_LOG']).write_text(json.dumps({'args': sys.argv[1:], 'prompt': os.environ.get('GIT_TERMINAL_PROMPT')}))\n"
        "sys.exit(1)\n"
    )
    ssh.chmod(0o755)
    monkeypatch.setenv("GIT_SSH_COMMAND", str(ssh))
    monkeypatch.setenv("SSH_TEST_LOG", str(log))
    git(project, "remote", "add", "origin", "ssh://example.invalid/report")

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    assert not log.exists(), "base discovery must use only local Git refs"


@pytest.mark.parametrize("rules", ["workspace.mk", "Makefile"])
@pytest.mark.parametrize(
    "destination", ["rendered output's directory", "literal$(exit 99)$name"]
)
def test_render_output_override_leaves_preview_output_alone(
    project: Path, tmp_path: Path, rules: str, destination: str
) -> None:
    result = subprocess.run(
        [
            "make",
            "-f",
            str(ASSETS / rules),
            "render",
            "ASTA_WORKSPACE_VIEWERS=0",
            f"ASTA_WORKSPACE_RENDER_OUTPUT={destination}",
        ],
        cwd=project,
        env=make_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "baseline finding" in (project / destination / "index.html").read_text()
    assert not (project / "_site").exists()


def rendered_pages(log: Path) -> list[list[str]]:
    return [
        [str(Path(page)) for page in json.loads(line)["pages"]]
        for line in log.read_text().splitlines()
    ]


def add_page(project: Path, name: str, text: str) -> None:
    (project / name).write_text(text)
    git(project, "add", "--", name)
    git(project, "commit", "-qm", f"add {name}")
    git(project, "branch", "-f", "main")


def test_page_edit_renders_only_changed_pages(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_page(project, "other.qmd", "An untouched page.\n")
    (project / "index.qmd").write_text("The baseline finding holds.\nA new line.\n")
    (project / "draft.qmd").write_text("A brand new page.\n")
    log = tmp_path / "quarto.log"
    monkeypatch.setenv("QUARTO_LOG", str(log))

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    assert rendered_pages(log) == [["index.qmd"], ["draft.qmd"], ["index.qmd"]]
    page = (project / "_site/what-changed.html").read_text()
    assert "A new line." in page
    assert "A brand new page." in page
    assert "An untouched page." not in page


def test_page_only_render_keeps_the_preview_site_theme(
    project: Path, tmp_path: Path
) -> None:
    deck = "<html><head><link href='../site_libs/revealjs/dist/reveal.css' rel='stylesheet'></head><body><div class='reveal'>Deck</div></body></html>"
    (project / "_site/talk").mkdir(parents=True)
    (project / "_site/talk/slides.html").write_text(deck)
    (project / "_site/index.html").write_text(
        '<html><head><link href="site_libs/bootstrap/bootstrap.min.css" '
        'rel="stylesheet"></head><body><main>Live preview.</main></body></html>'
    )
    (project / "index.qmd").write_text("The baseline finding holds.\nA new line.\n")

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "only pages changed" in result.stderr
    page = (project / "_site/what-changed.html").read_text()
    assert 'href="site_libs/bootstrap/bootstrap.min.css"' in page
    assert "reveal.css" not in page
    assert "A new line." in page


@pytest.mark.parametrize("full", [False, True])
def test_non_page_change_or_opt_out_renders_whole_site(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, full: bool
) -> None:
    add_page(project, "other.qmd", "An untouched page.\n")
    (project / "index.qmd").write_text("The baseline finding holds.\nA new line.\n")
    if not full:
        (project / "styles.css").write_text("p { color: red; }\n")
    log = tmp_path / "quarto.log"
    monkeypatch.setenv("QUARTO_LOG", str(log))

    result = make(project, tmp_path, *(["WHAT_CHANGED_FULL=1"] if full else []))

    assert result.returncode == 0, result.stderr
    assert rendered_pages(log) == [[], []]
    assert "A new line." in (project / "_site/what-changed.html").read_text()


def test_base_without_page_list_support_renders_whole_site(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A project whose own render rule predates the page list keeps full renders.
    workspace = (project / "workspace.mk").read_text()
    (project / "workspace.mk").write_text(
        workspace.replace("$(value ASTA_WORKSPACE_RENDER_FILES)", "").replace(
            "quarto render $(if", "quarto render . $(if"
        )
    )
    git(project, "commit", "-qam", "older rules")
    git(project, "branch", "-f", "main")
    (project / "index.qmd").write_text("The baseline finding holds.\nA new line.\n")
    log = tmp_path / "quarto.log"
    monkeypatch.setenv("QUARTO_LOG", str(log))

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    assert rendered_pages(log) == [[], []]


@pytest.mark.parametrize("version", ["current", "base"])
def test_prerequisite_printing_page_list_does_not_enable_partial_render(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    add_page(project, "other.qmd", "An untouched page.\n")
    use_legacy_cached_rules(project)
    cache = project / ".asta/cache/workspace.mk"
    supported_rules = cache.read_text()
    custom_rules = (
        (project / "workspace.mk")
        .read_text()
        .replace(
            "render: workspace-assets workspace-viewers\n\tquarto render\n",
            ".PHONY: show-render-files\n"
            "show-render-files:\n"
            "\t@echo '$(ASTA_WORKSPACE_RENDER_FILES)'\n"
            "render: workspace-assets workspace-viewers show-render-files\n"
            "\tquarto render . $(if $(value ASTA_WORKSPACE_RENDER_OUTPUT),"
            "--output-dir '$(value ASTA_WORKSPACE_RENDER_OUTPUT)')\n",
        )
    )
    (project / "workspace.mk").write_text(custom_rules)
    git(project, "commit", "-qam", "custom render ignores page list")
    git(project, "branch", "-f", "main")
    # Refresh after updating tracked rules so Make does not replace the ignored
    # cache based on mtimes. The base reconstructs its own custom rules.
    cache.write_text(custom_rules if version == "current" else supported_rules)
    (project / "index.qmd").write_text(
        "The baseline finding holds.\nA newly drafted paragraph.\n"
    )
    assert git(project, "diff", "--name-only", "main").strip() == "index.qmd"
    log = tmp_path / "quarto.log"
    monkeypatch.setenv("QUARTO_LOG", str(log))

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "only pages changed" not in result.stderr
    assert rendered_pages(log) == [[], []]
    report = (project / "_site/what-changed.html").read_text()
    assert "newly drafted paragraph" in report
    assert "other.html" not in report, "unchanged pages must not appear added/removed"


@pytest.mark.parametrize("rules", ["workspace.mk", "Makefile"])
def test_render_page_list_keeps_every_page(project: Path, tmp_path: Path, rules: str):
    (project / "second.qmd").write_text("Second page text.\n")
    destination = Path("rendered output")
    result = subprocess.run(
        [
            "make",
            "-f",
            str(ASSETS / rules),
            "render",
            "ASTA_WORKSPACE_VIEWERS=0",
            "ASTA_WORKSPACE_RENDER_FILES=index.qmd second.qmd",
            f"ASTA_WORKSPACE_RENDER_OUTPUT={destination}",
        ],
        cwd=project,
        env=make_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "baseline finding" in (project / destination / "index.html").read_text()
    assert "Second page" in (project / destination / "second.html").read_text()


@pytest.mark.skipif(shutil.which("quarto") is None, reason="needs real Quarto")
@pytest.mark.parametrize("configuration", ["explicit", "profile", "no-output"])
def test_real_quarto_rejects_custom_output_directory(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configuration: str
) -> None:
    """Resolved config, including active profiles, must match the served output."""
    (project / "_quarto.yml").write_text("project:\n  type: website\n")
    if configuration == "profile":
        (project / "_quarto-local.yml").write_text("project:\n  output-dir: docs\n")
        monkeypatch.setenv("QUARTO_PROFILE", "local")
    elif configuration == "explicit":
        (project / "_quarto.yml").write_text(
            "project:\n  type: website\n  output-dir: docs\n"
        )
    else:
        (project / "_quarto.yml").write_text("project:\n  type: default\n")
    (project / "docs").mkdir()
    preview = project / "docs/index.html"
    preview.write_text("Keep this live preview.")

    result = subprocess.run(
        ["make", "what-changed", "ASTA_WORKSPACE_VIEWERS=0"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "requires project.output-dir=_site in both versions" in result.stderr
    assert preview.read_text() == "Keep this live preview."
    assert not (project / "_site/what-changed.html").exists()
    assert git(project, "worktree", "list", "--porcelain").count("worktree ") == 1


@pytest.mark.skipif(shutil.which("quarto") is None, reason="needs real Quarto")
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("mode", ["partial", "full", "new-stylesheet"])
def test_real_quarto_slide_only_edit_keeps_site_theme(
    project: Path, tmp_path: Path, legacy: bool, mode: str
) -> None:
    """Local comparisons retain the actual theme without overwriting preview."""
    (project / "_quarto.yml").write_text(
        "project:\n  type: website\nformat:\n  html:\n"
        "    theme: cosmo\n    css: styles.css\n"
    )
    (project / "styles.css").write_text("body { letter-spacing: 0.01em; }\n")
    (project / ".gitignore").write_text(
        (project / ".gitignore").read_text() + "/.quarto/\n"
    )
    deck = project / "talk/deck.qmd"
    deck.parent.mkdir()
    deck.write_text(
        "---\ntitle: Research talk\nformat: revealjs\n---\n\n"
        "## Finding\n\nThe original finding.\n"
    )
    git(project, "add", "_quarto.yml", "styles.css", ".gitignore", "talk")
    git(project, "commit", "-qm", "themed site baseline")
    git(project, "branch", "-f", "main")
    if legacy:
        use_legacy_cached_rules(project)
    subprocess.run(
        ["quarto", "render", "index.qmd"],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    # Quarto versions add different cache exclusions on first render (1.11
    # also adds **/*.quarto_ipynb). Record only that setup in the baseline,
    # keeping the comparison page-only without hiding any other source edits.
    if git(project, "diff", "--name-only", "--", ".gitignore").strip():
        git(project, "add", ".gitignore")
        git(project, "commit", "-qm", "record Quarto preview cache exclusions")
        git(project, "branch", "-f", "main")
    assert git(project, "status", "--porcelain") == ""
    site = project / "_site"
    preview = (site / "index.html").read_text()
    # An unstyled generated landing page sorts before the themed index. Theme
    # lookup must continue to the index rather than falling back to deck CSS.
    unstyled = site / "a-unstyled.html"
    unstyled.write_text("<head></head><main>Unstyled landing page</main>")
    deck.write_text(deck.read_text().replace("original", "updated"))
    original_css = (site / "styles.css").read_text()
    if mode == "full":
        (project / "styles.css").write_text("body { letter-spacing: 0.123em; }\n")
    elif mode == "new-stylesheet":
        (project / "_quarto.yml").write_text(
            (project / "_quarto.yml")
            .read_text()
            .replace("css: styles.css", "css: fresh.css")
        )
        (project / "fresh.css").write_text("body { letter-spacing: 0.321em; }\n")

    result = subprocess.run(
        ["make", "what-changed", "ASTA_WORKSPACE_VIEWERS=0"],
        cwd=project,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    if mode == "partial":
        assert "only pages changed; rendering ./talk/deck.qmd" in result.stderr
    else:
        assert "only pages changed" not in result.stderr
    report = (site / "what-changed.html").read_text()
    assert "updated" in report
    assert "reveal.css" not in report
    css_links = re.findall(r'<link\b[^>]*href="([^"]+\.css)"', report)
    expected_css = "fresh.css" if mode == "new-stylesheet" else "styles.css"
    theme_css = (
        expected_css if mode == "partial" else "what-changed-assets/" + expected_css
    )
    assert theme_css in css_links
    assert any("site_libs/bootstrap/bootstrap" in href for href in css_links)
    if mode == "full":
        assert "0.123em" in (site / theme_css).read_text()
    elif mode == "new-stylesheet":
        assert "0.321em" in (site / theme_css).read_text()
        assert not (site / "fresh.css").exists()
    assert (site / "styles.css").read_text() == original_css
    for href in css_links:
        assert (site / href).is_file(), f"missing comparison stylesheet: {href}"
    assert (site / "index.html").read_text() == preview
    assert unstyled.read_text() == "<head></head><main>Unstyled landing page</main>"
    assert not list((project / ".asta/cache").glob("what-changed.*"))
    assert git(project, "worktree", "list", "--porcelain").count("worktree ") == 1


@pytest.mark.skipif(shutil.which("quarto") is None, reason="needs real Quarto")
@pytest.mark.parametrize("edit", ["page", "slides", "multiple"])
@pytest.mark.parametrize("legacy", [False, True])
def test_real_quarto_on_92_page_workspace(
    project: Path, tmp_path: Path, edit: str, legacy: bool
):
    """Exercise real CLI parsing, nested outputs, and timing on a grown site."""
    (project / "_quarto.yml").write_text(
        "project:\n  type: website\nformat:\n  html:\n    theme: none\n"
    )
    (project / ".gitignore").write_text(
        (project / ".gitignore").read_text() + ".quarto/\n"
    )
    pages = project / "pages"
    pages.mkdir()
    for number in range(90):
        (pages / f"page-{number}.qmd").write_text(
            f"---\ntitle: Page {number}\n---\n\nAn unchanged research page.\n"
        )
    deck = project / "talk/slides.qmd"
    deck.parent.mkdir()
    deck.write_text(
        "---\ntitle: Research talk\nformat: revealjs\n---\n\n"
        + "\n\n".join(
            f"## Slide {number}\n\n" + "Repeated research finding. " * 80
            for number in range(100)
        )
    )
    # workspace-assets detects slides.qmd by name; keep this fixture offline.
    extension = project / "_extensions/asta-slides/version.txt"
    extension.parent.mkdir()
    extension.write_text("Committed fixture extension.")
    git(project, "add", "-f", "_extensions/asta-slides/version.txt")
    git(project, "add", "_quarto.yml", ".gitignore", "pages", "talk")
    git(project, "commit", "-qm", "92-page baseline")
    git(project, "branch", "-f", "main")
    if legacy:
        use_legacy_cached_rules(project)
    if edit == "slides":
        deck.write_text(deck.read_text().replace("finding", "revisedfinding", 1))
        expected = ["revisedfinding"]
    else:
        (project / "index.qmd").write_text(
            "The baseline finding holds.\n\nA newly drafted paragraph.\n"
        )
        expected = ["newly drafted paragraph"]
        if edit == "multiple":
            (pages / "page-1.qmd").write_text("A separately revised page.\n")
            (project / "draft.qmd").write_text("A brand new draft page.\n")
            expected += ["separately revised page", "brand new draft page"]
    site = project / "_site"
    site.mkdir()
    (site / "index.html").write_text("Live preview output must stay intact.")
    temporary = tmp_path / "real-temporary"
    temporary.mkdir()
    started = time.monotonic()
    result = subprocess.run(
        ["make", "what-changed", "ASTA_WORKSPACE_VIEWERS=0"],
        cwd=project,
        env={**os.environ, "TMPDIR": str(temporary)},
        capture_output=True,
        text=True,
        timeout=90,
    )
    elapsed = time.monotonic() - started
    print(
        f"real Quarto: 92-page workspace, {edit} edit, legacy={legacy}: {elapsed:.2f}s"
    )
    assert result.returncode == 0, result.stderr
    assert "only pages changed" in result.stderr
    report = (site / "what-changed.html").read_text()
    # Inline diffs split phrases across <ins>/<del> tags. Check the new reading
    # with deletions removed, so replacements are tested as well as additions.
    current_text = html.unescape(
        re.sub(r"<[^>]+>", "", re.sub(r"(?s)<del\b[^>]*>.*?</del>", "", report))
    )
    for text in expected:
        assert text in current_text
    assert "<ins" in report
    assert "An unchanged research page" not in report
    assert (site / "index.html").read_text() == "Live preview output must stay intact."
    assert not list(temporary.iterdir())
    assert not list((project / ".asta/cache").glob("what-changed.*"))
    assert git(project, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert elapsed < 45, f"local comparison took {elapsed:.2f}s"


@pytest.mark.skipif(shutil.which("quarto") is None, reason="needs real Quarto")
def test_real_quarto_with_ignored_theme_installed_by_base_rules(
    project: Path, tmp_path: Path
) -> None:
    """The historical worktree must install its missing managed theme itself."""
    git(project, "rm", "--cached", "_extensions/evidence/version.txt")
    shutil.rmtree(project / "_extensions")
    archive = tmp_path / "extensions.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(
            ASSETS / "_extensions",
            arcname="release/plugins/asta-tools/skills/workspace/assets/_extensions",
        )
    with (project / "Makefile").open("a") as file:
        file.write(f"ASTA_PLUGINS_ARCHIVE_URL := {archive.as_uri()}\n")
    (project / "_quarto.yml").write_text(
        "project:\n  type: website\nformat:\n  html:\n"
        "    theme: [cosmo, _extensions/asta-theme/light.scss]\n"
        "    css: _extensions/asta-theme/asta.css\n"
        "    include-in-header: _extensions/asta-theme/asta-head.html\n"
    )
    with (project / ".gitignore").open("a") as file:
        file.write("/.quarto/\n")
    git(project, "add", "Makefile", "_quarto.yml", ".gitignore")
    git(project, "commit", "-qm", "managed theme installed from the selected archive")
    git(project, "branch", "-f", "main")
    (project / "index.qmd").write_text("A newly drafted paragraph.\n")
    site = project / "_site"
    site.mkdir()
    (site / "index.html").write_text("The live preview stays intact.")
    temporary = tmp_path / "real-temporary"
    temporary.mkdir()

    result = subprocess.run(
        ["make", "what-changed", "ASTA_WORKSPACE_VIEWERS=0"],
        cwd=project,
        env={**os.environ, "TMPDIR": str(temporary)},
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr
    assert "only pages changed" in result.stderr
    report = (site / "what-changed.html").read_text()
    assert "drafted" in report
    # Quarto versions relocate extension CSS differently (for example into
    # site_libs/quarto-contrib/quarto-project/). Follow the rendered link rather
    # than assuming that the source extension's directory survives publication.
    theme_links = re.findall(
        r'<link\b[^>]*\bhref="([^"]*/asta-theme/asta\.css)"', report
    )
    assert theme_links, report
    for href in theme_links:
        assert href.startswith("what-changed-assets/"), href
        published_css = site / html.unescape(href)
        assert published_css.is_file(), href
        assert (
            published_css.read_text()
            == (ASSETS / "_extensions/asta-theme/asta.css").read_text()
        )
    assert (site / "index.html").read_text() == "The live preview stays intact."
    assert not list(temporary.iterdir())
    assert not list((project / ".asta/cache").glob("what-changed.*"))
    assert git(project, "worktree", "list", "--porcelain").count("worktree ") == 1


def use_legacy_cached_rules(project: Path):
    """An ignored sync refresh updates current rules, while the base keeps its own."""
    current = (project / "workspace.mk").read_text()
    start = current.index("\tset -eu;", current.index("render: workspace-assets"))
    end = current.index("\n\n", start)
    legacy = current[:start] + "\tquarto render" + current[end:]
    (project / "workspace.mk").write_text(legacy)
    (project / "Makefile").write_text(
        ".asta/cache/workspace.mk: workspace.mk\n"
        "\t@mkdir -p .asta/cache\n"
        "\tcp workspace.mk .asta/cache/workspace.mk\n"
        "include .asta/cache/workspace.mk\n"
    )
    git(project, "add", "workspace.mk", "Makefile")
    git(project, "commit", "-qm", "legacy managed workspace")
    git(project, "branch", "-f", "main")
    cache = project / ".asta/cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "workspace.mk").write_text(current)


def test_legacy_plain_quarto_render_gets_page_selection(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    add_page(project, "other.qmd", "An untouched page.\n")
    use_legacy_cached_rules(project)
    (project / "index.qmd").write_text("The baseline finding holds.\nA new line.\n")
    (project / "draft.qmd").write_text("A brand new page.\n")
    log = tmp_path / "quarto.log"
    monkeypatch.setenv("QUARTO_LOG", str(log))
    result = make(project, tmp_path)
    assert result.returncode == 0, result.stderr
    assert rendered_pages(log) == [["index.qmd"], ["draft.qmd"], ["index.qmd"]]
    page = (project / "_site/what-changed.html").read_text()
    assert "A new line." in page and "A brand new page." in page
    assert "An untouched page." not in page


@pytest.mark.parametrize("at_base", [False, True])
def test_missing_project_configuration_fails_before_rendering(
    project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    at_base: bool,
) -> None:
    if at_base:
        git(project, "rm", "_quarto.yml")
        git(project, "commit", "-qm", "baseline without a Quarto project")
        git(project, "branch", "-f", "main")
        (project / "_quarto.yml").write_text("project:\n  type: website\n")
    else:
        (project / "_quarto.yml").unlink()
    log = tmp_path / "quarto.log"
    monkeypatch.setenv("QUARTO_LOG", str(log))
    result = make(project, tmp_path)
    assert result.returncode != 0
    assert "missing Quarto project configuration" in result.stderr
    assert not log.exists()
    assert not (project / "_site/what-changed.html").exists()
    assert not list((tmp_path / "temporary").iterdir())
    assert git(project, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_page_name_starting_with_dash_is_not_a_quarto_option(
    project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_page(project, "-draft.qmd", "A previous finding.\n")
    (project / "-draft.qmd").write_text("A newly drafted paragraph.\n")
    log = tmp_path / "quarto.log"
    monkeypatch.setenv("QUARTO_LOG", str(log))
    result = make(project, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "only pages changed" in result.stderr
    assert rendered_pages(log) == [["-draft.qmd"], ["-draft.qmd"]]
    assert "drafted" in (project / "_site/what-changed.html").read_text()


@pytest.mark.parametrize("version", ["current", "base"])
def test_page_excluded_by_either_inspected_project_uses_full_render(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    add_page(project, "notes.qmd", "An excluded research note.\n")
    (project / "notes.qmd").write_text("A revised research note.\n")
    scope = str(project) if version == "current" else "base"
    monkeypatch.setenv("QUARTO_EXCLUDED_INPUTS", json.dumps({scope: ["notes.qmd"]}))
    log = tmp_path / "quarto.log"
    monkeypatch.setenv("QUARTO_LOG", str(log))

    result = make(project, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "only pages changed" not in result.stderr
    assert rendered_pages(log) == [[], []]


@pytest.mark.parametrize("flags", [["-n"], ["--just-print"], ["-kn"]])
def test_dry_run_creates_no_worktrees_or_output(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: list[str]
) -> None:
    log = tmp_path / "quarto.log"
    monkeypatch.setenv("QUARTO_LOG", str(log))
    result = make(project, tmp_path, *flags)
    assert result.returncode == 0, result.stderr
    assert "dry run; no renders or worktrees created" in result.stdout
    assert not log.exists()
    assert not (project / "_site").exists()
    assert not (project / ".asta/cache").exists()
    assert not list((tmp_path / "temporary").iterdir())
    assert git(project, "worktree", "list", "--porcelain").count("worktree ") == 1


@pytest.mark.parametrize("rules", ["workspace.mk", "Makefile"])
def test_direct_render_page_list_does_not_glob_or_parse_names_as_options(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rules: str
) -> None:
    for name in ("star*.qmd", "star-other.qmd", "-draft.qmd"):
        (project / name).write_text("A research page.\n")
    log = tmp_path / "quarto.log"
    monkeypatch.setenv("QUARTO_LOG", str(log))
    result = subprocess.run(
        [
            "make",
            "-f",
            str(ASSETS / rules),
            "render",
            "ASTA_WORKSPACE_VIEWERS=0",
            "ASTA_WORKSPACE_RENDER_FILES=star*.qmd -draft.qmd",
            "ASTA_WORKSPACE_RENDER_OUTPUT=render-output",
        ],
        cwd=project,
        env=make_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert rendered_pages(log) == [["star*.qmd"], ["-draft.qmd"]]


@pytest.mark.skipif(shutil.which("quarto") is None, reason="needs real Quarto")
@pytest.mark.parametrize("excluded", ["README.md", "notes.qmd"])
def test_real_quarto_render_allowlist_does_not_publish_excluded_pages(
    project: Path, tmp_path: Path, excluded: str
) -> None:
    (project / "_quarto.yml").write_text(
        "project:\n  type: website\n  render:\n    - index.qmd\n"
        "format:\n  html:\n    theme: none\n"
    )
    (project / excluded).write_text("An excluded finding.\n")
    # Quarto 1.7 creates this cache without adding an ignore entry. Keep it
    # out of source selection on every supported version.
    (project / ".gitignore").write_text(
        (project / ".gitignore").read_text() + "/.quarto/\n"
    )
    # Inspection can add other version-specific cache ignores. Record that setup
    # before the baseline so an unrelated .gitignore edit cannot force full
    # rendering and accidentally make this regression pass.
    subprocess.run(
        ["quarto", "inspect", "."],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    git(project, "add", "_quarto.yml", ".gitignore", excluded)
    git(project, "commit", "-qm", "site with an explicit render allowlist")
    git(project, "branch", "-f", "main")
    assert git(project, "status", "--porcelain") == ""
    (project / excluded).write_text("A revised excluded finding.\n")
    temporary = tmp_path / "real-temporary"
    temporary.mkdir()
    result = subprocess.run(
        ["make", "what-changed", "ASTA_WORKSPACE_VIEWERS=0"],
        cwd=project,
        env={**os.environ, "TMPDIR": str(temporary)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "only pages changed" not in result.stderr
    report = (project / "_site/what-changed.html").read_text()
    assert "No rendered content changed" in report
    assert "excluded finding" not in report
    assert not (project / "_site" / Path(excluded).with_suffix(".html")).exists()
    assert not list(temporary.iterdir())
    assert git(project, "worktree", "list", "--porcelain").count("worktree ") == 1
