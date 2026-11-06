"""`make what-changed` writes a local What changed page into `_site/` before any PR."""

import html
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

ASSETS = Path(__file__).parent.parent / "plugins/asta-tools/skills/workspace/assets"

# Models the single positional input and project-relative output directory from
# Quarto's CLI contract; QUARTO_LOG records each individual invocation.
FAKE_QUARTO = """#!/usr/bin/env python3
import json, os, pathlib, re, sys, time
args = sys.argv[1:]
if args[0] == "inspect":
    config = pathlib.Path(args[1]) / "_quarto.yml"
    match = re.search(r"output-dir:\\s*([^\\s]+)", config.read_text())
    print(json.dumps({"config": {"project": {"output-dir": match[1] if match else "_site"}}}))
    sys.exit(0)
assert args[0] == "render", sys.argv
output = pathlib.Path("_site")
if "--output-dir" in args:
    index = args.index("--output-dir")
    output = pathlib.Path(args[index + 1])
    args = args[:index]
pages = [arg for arg in args[1:] if arg != "--no-clean"]
assert len(pages) <= 1, sys.argv
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
for page in pages or sorted(str(p) for p in pathlib.Path().glob("*.qmd")):
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
    git(project, "init", "-q", "-b", "main")
    (project / "_extensions/evidence").mkdir(parents=True)
    (project / "_extensions/evidence/version.txt").write_text("Baseline extension.")
    git(
        project, "add", "Makefile", "workspace.mk", "scripts", ".gitignore", "index.qmd"
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
def test_custom_current_render_cannot_overwrite_preview(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, full: bool
) -> None:
    with (project / "Makefile").open("a") as file:
        file.write("render:\n\tquarto render\n")
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
    assert (
        "current render recipe must honour ASTA_WORKSPACE_RENDER_OUTPUT"
        in result.stderr
    )
    assert live.read_text() == "Live preview must stay intact."
    assert not (site / "what-changed.html").exists()
    assert not log.exists(), "reject an unsafe recipe before either render runs"
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
    for name in ("Makefile", "workspace.mk", "scripts", "index.qmd", "_extensions"):
        git(project, "mv", name, str(nested.relative_to(project) / name))
    git(project, "commit", "-qm", "move report into a subdirectory")
    git(project, "branch", "-f", "main")
    (nested / "index.qmd").write_text("A newly drafted paragraph.\n")

    result = make(nested, tmp_path)

    assert result.returncode == 0, result.stderr
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
    return [json.loads(line)["pages"] for line in log.read_text().splitlines()]


def add_page(project: Path, name: str, text: str) -> None:
    (project / name).write_text(text)
    git(project, "add", name)
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
        workspace.replace("set -- $(ASTA_WORKSPACE_RENDER_FILES);", "set --;").replace(
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
def test_real_quarto_slide_only_edit_keeps_site_theme(
    project: Path, tmp_path: Path, legacy: bool
) -> None:
    """A deck-only comparison borrows real site CSS with working asset URLs."""
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
    # Quarto adds /.quarto/ on its first render if absent. Keep that setup
    # out of the comparison so this regression exercises the page-only path.
    assert git(project, "status", "--porcelain") == ""
    site = project / "_site"
    preview = (site / "index.html").read_text()
    deck.write_text(deck.read_text().replace("original", "updated"))

    result = subprocess.run(
        ["make", "what-changed", "ASTA_WORKSPACE_VIEWERS=0"],
        cwd=project,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "only pages changed; rendering talk/deck.qmd" in result.stderr
    report = (site / "what-changed.html").read_text()
    assert "updated" in report
    assert "reveal.css" not in report
    css_links = re.findall(r'<link\b[^>]*href="([^"]+\.css)"', report)
    assert "styles.css" in css_links
    assert any("site_libs/bootstrap/bootstrap" in href for href in css_links)
    for href in css_links:
        assert (site / href).is_file(), f"missing comparison stylesheet: {href}"
    assert (site / "index.html").read_text() == preview
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
