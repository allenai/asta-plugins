"""`asta workspace bump-pin` moves a release pin behind asta to its release."""

import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from asta.cli import cli
from asta.commands import workspace, workspace_versions
from tests._workspace_helpers import _archive

pytestmark = pytest.mark.usefixtures("pinned_workspace")

STUB = (
    "jobs:\n"
    "  docs:\n"
    "    # uses: allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@v0.1.0\n"
    "    uses: allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@{ref}"
    "  # pinned\n"
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def project(tmp_path: Path):
    def make(ref: str) -> Path:
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "t@example.com")
        _git(tmp_path, "config", "user.name", "t")
        workflow = tmp_path / ".github/workflows/docs.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(STUB.format(ref=ref))
        (tmp_path / "notes.md").write_text("x\n")
        _git(tmp_path, "add", ".github/workflows/docs.yml", "notes.md")
        _git(tmp_path, "commit", "-q", "-m", "init")
        return tmp_path

    return make


def _run(root: Path, version: str, monkeypatch, *, catch_exceptions=False):
    monkeypatch.setattr(workspace_versions, "installed", lambda: version)
    return CliRunner().invoke(
        cli,
        ["workspace", "bump-pin", "--project", str(root)],
        catch_exceptions=catch_exceptions,
    )


@pytest.mark.parametrize(
    ("ref", "cli_version", "expected"),
    [
        ("v0.115.0", "0.116.0", "v0.116.0"),
        ("0.115.0", "0.116.0", "0.116.0"),
        ("v0.116.0", "0.116.0", None),
        ("v0.117.0", "0.116.0", None),
        ("v0.115.0", "0.117.0.dev0", None),
        ("v0.115.0", "0.117.0rc1", None),
        ("main", "0.116.0", None),
        ("latest", "0.116.0", None),
        ("a" * 40, "0.116.0", None),
    ],
)
def test_pin_target(ref, cli_version, expected) -> None:
    assert workspace_versions.pin_target(ref, cli_version) == expected


def test_behind_pin_moves_in_its_own_commit(project, monkeypatch) -> None:
    root = project("v0.115.0")
    (root / "notes.md").write_text("work in progress\n")
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code == 0, result.output
    text = (root / ".github/workflows/docs.yml").read_text()
    assert "workspace-quarto-site.yml@v0.116.0  # pinned\n" in text
    assert (
        "# uses: allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@v0.1.0"
        in text
    )
    assert _git(root, "show", "--name-only", "--format=%s", "HEAD").split() == [
        "Move",
        "workspace",
        "pin",
        "to",
        "asta-plugins@v0.116.0",
        ".github/workflows/docs.yml",
    ]
    assert "notes.md" in _git(root, "status", "--porcelain")
    assert f"Committed {_git(root, 'rev-parse', 'HEAD').strip()}:" in result.output


@pytest.mark.parametrize("ref", ["v0.116.0", "main"])
def test_current_or_unpinned_ref_is_left_alone(project, monkeypatch, ref) -> None:
    root = project(ref)
    head = _git(root, "rev-parse", "HEAD")
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code == 0
    assert "nothing to do" in result.output
    assert _git(root, "rev-parse", "HEAD") == head


def test_uncommitted_workflow_edit_refuses(project, monkeypatch) -> None:
    root = project("v0.115.0")
    workflow = root / ".github/workflows/docs.yml"
    workflow.write_text(workflow.read_text() + "# local edit\n")
    head = _git(root, "rev-parse", "HEAD")
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "uncommitted changes" in result.output
    assert _git(root, "rev-parse", "HEAD") == head


def test_non_git_project_is_unchanged(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    workflow = tmp_path / ".github/workflows/docs.yml"
    workflow.parent.mkdir(parents=True)
    original = STUB.format(ref="v0.115.0").encode()
    workflow.write_bytes(original)
    result = _run(tmp_path, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "Could not check" in result.output
    assert workflow.read_bytes() == original


def test_failed_git_status_leaves_workflow_unchanged(project, monkeypatch) -> None:
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    original = workflow.read_bytes()
    monkeypatch.setattr(
        workspace,
        "_git",
        lambda *args: subprocess.CompletedProcess(args, 128, "", "Git failed"),
    )
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "Git failed" in result.output
    assert workflow.read_bytes() == original


@pytest.mark.parametrize(
    "relative", [".github", ".github/workflows", workspace.WORKFLOW_FILE]
)
def test_symlink_in_workflow_path_is_rejected(
    project, tmp_path_factory, monkeypatch, relative
) -> None:
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    original = workflow.read_bytes()
    linked = root / relative
    external = tmp_path_factory.mktemp("external") / "target"
    linked.rename(external)
    linked.symlink_to(external, target_is_directory=external.is_dir())
    _git(root, "add", "--", relative)
    _git(root, "commit", "-q", "-m", "Link workflow path")
    head = _git(root, "rev-parse", "HEAD")
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "symlinks" in result.output
    assert linked.is_symlink()
    assert workflow.read_bytes() == original
    assert _git(root, "rev-parse", "HEAD") == head
    assert not _git(root, "status", "--porcelain")


@pytest.mark.parametrize("site_dir", [".", "research/site"])
def test_rejected_commit_restores_workflow_and_preserves_other_work(
    project, monkeypatch, site_dir
) -> None:
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    site = root / site_dir
    site.mkdir(parents=True, exist_ok=True)
    if site_dir != ".":
        workflow.write_text(
            workflow.read_text() + f"    with:\n      site-dir: {site_dir}\n"
        )
    original = workflow.read_bytes().replace(b"\n", b"\r\n")
    workflow.write_bytes(original)
    _git(root, "add", workspace.WORKFLOW_FILE)
    _git(root, "commit", "-q", "-m", "Use CRLF")
    head = _git(root, "rev-parse", "HEAD")
    notes = root / "notes.md"
    notes.write_text("staged work\n")
    _git(root, "add", "notes.md")
    notes.write_text("unstaged work\n")
    staged = _git(root, "diff", "--cached")
    hook = root / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\necho 'commit rejected' >&2\nexit 1\n")
    hook.chmod(0o755)
    result = _run(site, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "commit rejected" in result.output
    assert workflow.read_bytes() == original
    assert _git(root, "rev-parse", "HEAD") == head
    assert _git(root, "diff", "--cached") == staged
    assert notes.read_text() == "unstaged work\n"
    if site_dir != ".":
        assert not (site / ".github").exists()


def test_failed_validation_restores_workflow(project, monkeypatch) -> None:
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    original = workflow.read_bytes()
    selected_source = workspace._source_from_workflow

    def validate(workflow):
        if b"@v0.116.0" in workflow.read_bytes():
            raise click.ClickException("validation failed")
        return selected_source(workflow)

    monkeypatch.setattr(workspace, "_source_from_workflow", validate)
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "validation failed" in result.output
    assert workflow.read_bytes() == original
    assert not _git(root, "status", "--porcelain")


def test_atomic_pin_write_failure_leaves_workflow_unchanged(
    project, monkeypatch
) -> None:
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    original = workflow.read_bytes()
    atomic_write = workspace._atomic_write

    def write(path, data):
        if path == workflow and data != original:
            raise OSError("write failed")
        return atomic_write(path, data)

    monkeypatch.setattr(workspace, "_atomic_write", write)
    result = _run(root, "0.116.0", monkeypatch, catch_exceptions=True)
    assert result.exit_code != 0
    assert workflow.read_bytes() == original
    assert not _git(root, "status", "--porcelain")


@pytest.mark.parametrize("quote", ["", "'", '"'])
@pytest.mark.parametrize("reuse_job", [False, True])
def test_all_matching_workflow_refs_move_without_changing_other_text(
    project, monkeypatch, quote, reuse_job
) -> None:
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    source = f"allenai/asta-plugins{workspace.WORKFLOW}v0.115.0"
    first = "  first: &publishing\r\n" if reuse_job else "  first:\r\n"
    second = (
        "  second: *publishing\r\n"
        if reuse_job
        else f"  second:\r\n    uses: {quote}{source}{quote} # second\r\n"
    )
    original = (
        f"jobs:\r\n{first}    uses: {quote}{source}{quote} # first\r\n"
        f"{second}# uses: {source}0\r\n"
    ).encode()
    workflow.write_bytes(original)
    _git(root, "add", workspace.WORKFLOW_FILE)
    _git(root, "commit", "-q", "-m", "Repeat workflow source")
    result = _run(root, "0.116.10", monkeypatch)
    assert result.exit_code == 0, result.output
    assert workflow.read_bytes() == original.replace(
        b"v0.115.0", b"v0.116.10", 1 if reuse_job else 2
    )
    assert not _git(root, "status", "--porcelain")


@pytest.mark.parametrize("other_ref", ["v0.1.10", "v0.2.0"])
def test_mixed_refs_are_rejected_before_writing(project, monkeypatch, other_ref):
    root = project("v0.1.1")
    workflow = root / workspace.WORKFLOW_FILE
    original = (
        workflow.read_bytes()
        + (
            f"  other:\n    uses: allenai/asta-plugins{workspace.WORKFLOW}{other_ref}\n"
        ).encode()
    )
    workflow.write_bytes(original)
    _git(root, "add", workspace.WORKFLOW_FILE)
    _git(root, "commit", "-q", "-m", "Use different refs")
    head = _git(root, "rev-parse", "HEAD")
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "Expected one asta-plugins workspace source" in result.output
    assert workflow.read_bytes() == original
    assert _git(root, "rev-parse", "HEAD") == head
    assert not _git(root, "status", "--porcelain")


@pytest.mark.parametrize("committed", [False, True])
def test_interrupted_commit_only_restores_when_head_did_not_advance(
    project, monkeypatch, committed
):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    original = workflow.read_bytes()
    head = _git(root, "rev-parse", "HEAD")
    run_git = workspace._git

    def interrupt(project, *args):
        if args[0] == "commit":
            if committed:
                assert run_git(project, *args).returncode == 0
            raise KeyboardInterrupt
        return run_git(project, *args)

    monkeypatch.setattr(workspace, "_git", interrupt)
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    expected = original.replace(b"@v0.115.0", b"@v0.116.0") if committed else original
    assert workflow.read_bytes() == expected
    assert (_git(root, "rev-parse", "HEAD") != head) is committed
    assert ("Committed " in result.output) is committed
    assert not _git(root, "status", "--porcelain")


def test_invalid_workflow_encoding_has_clear_error(project, monkeypatch):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    original = workflow.read_bytes() + b"# invalid: \xff\n"
    workflow.write_bytes(original)
    head = _git(root, "rev-parse", "HEAD")
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "Workflow must be UTF-8" in result.output
    assert workflow.read_bytes() == original
    assert _git(root, "rev-parse", "HEAD") == head


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("unreadable", ["exit", "oserror"])
def test_unreadable_head_after_failure_warns_without_guessing_rollback(
    project, monkeypatch, committed, unreadable
):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    run_git = workspace._git
    commit_started = False

    def fail(project, *args):
        nonlocal commit_started
        if args[0] == "commit":
            commit_started = True
            if committed:
                assert run_git(project, *args).returncode == 0
            raise KeyboardInterrupt
        if args == ("rev-parse", "HEAD") and commit_started:
            if unreadable == "oserror":
                raise OSError("Git unavailable")
            return subprocess.CompletedProcess(args, 128, "", "Git unavailable")
        return run_git(project, *args)

    monkeypatch.setattr(workspace, "_git", fail)
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "Could not determine whether the pin move committed" in result.output
    assert "docs.yml may still be modified" in result.output
    assert "Inspect Git HEAD" in result.output
    assert "no rollback was attempted" in result.output
    assert "Committed " not in result.output
    assert b"@v0.116.0" in workflow.read_bytes()
    assert bool(_git(root, "status", "--porcelain")) is not committed


def test_unreadable_head_after_success_never_prints_an_empty_sha(project, monkeypatch):
    root = project("v0.115.0")
    run_git = workspace._git
    committed = False

    def fail(project, *args):
        nonlocal committed
        if args == ("rev-parse", "HEAD") and committed:
            return subprocess.CompletedProcess(args, 128, "", "Git unavailable")
        result = run_git(project, *args)
        if args[0] == "commit":
            committed = True
        return result

    monkeypatch.setattr(workspace, "_git", fail)
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "Could not determine whether the pin move committed" in result.output
    assert "Committed " not in result.output
    assert "@v0.116.0" in _git(root, "show", "HEAD:" + workspace.WORKFLOW_FILE)
    assert not _git(root, "status", "--porcelain")


@pytest.mark.skipif(not shutil.which("make"), reason="requires GNU Make")
@pytest.mark.parametrize("site_dir", [".", "research/site", "research/site notes"])
@pytest.mark.parametrize("checkout_spaces", [False, True])
def test_make_checks_bumped_rules_and_reloads_old_rules_after_revert(
    project, monkeypatch, tmp_path_factory, site_dir, checkout_spaces
):
    repository = project("v0.115.0")
    if checkout_spaces:
        repository = repository.rename(
            tmp_path_factory.mktemp("checkout") / "checkout with spaces"
        )
    root = repository / site_dir
    root.mkdir(parents=True, exist_ok=True)
    if site_dir != ".":
        workflow = repository / workspace.WORKFLOW_FILE
        workflow.write_text(
            workflow.read_text() + f"    with:\n      site-dir: {site_dir}\n"
        )
        _git(repository, "add", workspace.WORKFLOW_FILE)
    repo = Path(__file__).resolve().parents[1]
    assets = repo / "plugins/asta-tools/skills/workspace/assets"
    (root / "Makefile").write_bytes((assets / "Makefile.managed").read_bytes())
    (root / ".gitignore").write_text(".asta/cache/\n")
    _git(root, "add", "Makefile", ".gitignore")
    _git(root, "commit", "-q", "-m", "Use managed rules")

    # Use real sync/cache and Makefile behavior with controlled release assets.
    tools = tmp_path_factory.mktemp("sync-cli")
    helper = tools / "sync.py"
    helper.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(repo / 'src')!r})\n"
        "from asta.cli import cli\n"
        "from asta.commands import workspace, workspace_versions\n"
        "workspace_versions.installed = lambda: '0.116.0'\n"
        "def load_asset(repository, ref):\n"
        "    status = 1 if ref == 'v0.116.0' else 0\n"
        "    rules = f'.PHONY: check\\ncheck:\\n\\t@echo checked-{ref}\\n\\t@exit {status}\\n'\n"
        "    return rules.encode(), ref.encode()\n"
        "workspace.load_asset = load_asset\n"
        "workspace.load_scripts = lambda archive: {}\n"
        "cli()\n"
    )
    executable = tools / "asta"
    executable.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(helper))} "$@"\n'
    )
    executable.chmod(0o755)
    env = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"]}
    for name in ("ASTA_WORKSPACE_RESOLVED_SHA", "ASTA_WORKSPACE_RESOLVED_REPOSITORY"):
        env.pop(name, None)

    def check():
        return subprocess.run(
            ["make", "check"], cwd=root, env=env, text=True, capture_output=True
        )

    before = check()
    assert before.returncode == 0, before.stderr
    assert "checked-v0.115.0" in before.stdout
    if site_dir != ".":
        cached = check()
        assert cached.returncode == 0, cached.stderr
        assert "workspace.mk already cached" not in cached.stdout
        assert "checked-v0.115.0" in cached.stdout
    # Force a strict timestamp ordering even on coarse-resolution filesystems.
    old = time.time() - 10
    os.utime(repository / workspace.WORKFLOW_FILE, (old - 1, old - 1))
    os.utime(root / ".asta/cache/workspace.mk", (old, old))
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code == 0, result.output
    bump_sha = _git(root, "rev-parse", "HEAD").strip()
    after = check()
    assert after.returncode != 0
    assert "Loaded workspace.mk from asta-plugins@v0.116.0" in after.stdout
    assert "checked-v0.116.0" in after.stdout
    os.utime(root / ".asta/cache/workspace.mk", (old, old))
    _git(root, "revert", "--no-edit", bump_sha)
    restored = check()
    assert restored.returncode == 0, restored.stderr
    assert "Loaded workspace.mk from asta-plugins@v0.115.0" in restored.stdout
    assert "checked-v0.115.0" in restored.stdout
    assert not _git(root, "status", "--porcelain")
    if site_dir != ".":
        assert not (root / ".github").exists()


@pytest.mark.parametrize("git_marker", ["directory", "file"])
@pytest.mark.parametrize(
    ("site_dir", "site_value"),
    [
        ("research/site", "'./research/site/'"),
        ("research/site notes", "'./research/site notes/'"),
        ("research/site notes", '"./research/site notes/"'),
        ("research/site notes", "./research/site notes/"),
        ("research/site #1", "'./research/site #1/'"),
        ("research/site #1", '"./research/site #1/"'),
        ("research/site#1", "./research/site#1/"),
        ("research/site's notes", "'./research/site''s notes/'"),
    ],
)
def test_subfolder_site_moves_the_root_workflow_naming_it(
    tmp_path, monkeypatch, tmp_path_factory, git_marker, site_dir, site_value
):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    if git_marker == "file":
        git_data = tmp_path_factory.mktemp("git-data") / "repo.git"
        (tmp_path / ".git").rename(git_data)
        (tmp_path / ".git").write_text(f"gitdir: {git_data}\n")
    workflow = tmp_path / workspace.WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        STUB.format(ref="v0.115.0")
        + f"    with:\n      site-dir: {site_value} # site path\n"
    )
    site = tmp_path / site_dir
    site.mkdir(parents=True)
    (site / "index.qmd").write_text("x\n")
    _git(tmp_path, "add", workspace.WORKFLOW_FILE, str(site.relative_to(tmp_path)))
    _git(tmp_path, "commit", "-q", "-m", "init")
    assert workspace.workflow_root(site) == tmp_path.resolve()
    assert workspace.selected_source(site)[1] == "v0.115.0"
    result = _run(site, "0.116.0", monkeypatch)
    assert result.exit_code == 0, result.output
    assert "workspace-quarto-site.yml@v0.116.0  # pinned\n" in workflow.read_text()
    assert not (site / ".github").exists()
    assert not _git(tmp_path, "status", "--porcelain")


def test_root_workflow_naming_another_site_is_not_used(tmp_path):
    workflow = tmp_path / workspace.WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        STUB.format(ref="v0.115.0") + "    with:\n      site-dir: other\n"
    )
    (tmp_path / ".git").mkdir()
    site = tmp_path / "research/site"
    site.mkdir(parents=True)
    assert workspace.workflow_root(site) == site.resolve()
    with pytest.raises(click.ClickException, match="Missing"):
        workspace.selected_source(site)


@pytest.mark.parametrize("root_matches", [False, True])
def test_intermediate_workflow_does_not_publish_site(tmp_path, root_matches):
    (tmp_path / ".git").mkdir()
    site = tmp_path / "research/site"
    site.mkdir(parents=True)
    root_workflow = tmp_path / workspace.WORKFLOW_FILE
    root_workflow.parent.mkdir(parents=True)
    root_workflow.write_text(
        STUB.format(ref="v0.115.0")
        + f"    with:\n      site-dir: {'research/site' if root_matches else 'other'}\n"
    )
    intermediate = tmp_path / "research" / workspace.WORKFLOW_FILE
    intermediate.parent.mkdir(parents=True)
    intermediate.write_text(
        STUB.format(ref="v0.114.0") + "    with:\n      site-dir: site\n"
    )
    local = site / workspace.WORKFLOW_FILE
    local.parent.mkdir(parents=True)
    local.write_text(STUB.format(ref="v0.113.0"))
    assert workspace.workflow_root(site) == (tmp_path if root_matches else site)
    assert workspace.selected_source(site)[1] == (
        "v0.115.0" if root_matches else "v0.113.0"
    )


def test_non_git_site_ignores_ancestor_workflow(tmp_path):
    site = tmp_path / "research/site"
    site.mkdir(parents=True)
    workflow = tmp_path / workspace.WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        STUB.format(ref="v0.115.0") + "    with:\n      site-dir: research/site\n"
    )
    assert workspace.workflow_root(site) == site


@pytest.mark.parametrize("other_job", ["source", "both"])
@pytest.mark.parametrize("command", ["sync", "bump-pin"])
def test_subfolder_rejects_ambiguous_root_without_changing_pins(
    project, monkeypatch, other_job, command
):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    text = workflow.read_text() + "    with:\n      site-dir: site\n  other:\n"
    if other_job in ("source", "both"):
        text += f"    uses: allenai/asta-plugins{workspace.WORKFLOW}v0.115.0\n"
    if other_job == "both":
        text += "    with:\n      site-dir: other\n"
    workflow.write_text(text)
    site = root / "site"
    site.mkdir()
    monkeypatch.setattr(workspace_versions, "installed", lambda: "0.116.0")
    monkeypatch.setattr(
        workspace, "load_asset", lambda *_: pytest.fail("must reject before fetch")
    )
    head = _git(root, "rev-parse", "HEAD")
    result = CliRunner().invoke(cli, ["workspace", command, "--project", str(site)])
    assert result.exit_code != 0
    assert "Ambiguous workspace workflow" in result.output
    assert workflow.read_text() == text
    assert _git(root, "rev-parse", "HEAD") == head
    assert not (site / ".github").exists()


UNRELATED_SITE_INPUTS = [
    "  other:\n    uses: example/custom/.github/workflows/site.yml@main\n"
    "    with:\n      site-dir: site\n",
    "  other:\n    uses: example/custom/.github/workflows/workspace-quarto-site.yml@main\n"
    "    with:\n      site-dir: site\n",
    "    env:\n      site-dir: site\n",
    "    steps:\n      - uses: example/action@main\n"
    "        with:\n          site-dir: site\n",
    "    steps:\n      - run: |\n          site-dir: site\n",
    "env:\n  site-dir: site\n",
    "with:\n  site-dir: site\n",
]


@pytest.mark.parametrize("repository", ["example/asta-plugins", "Example/Asta-Plugins"])
def test_subfolder_accepts_a_fork_workflow(project, monkeypatch, repository):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    workflow.write_text(
        workflow.read_text().replace("allenai/asta-plugins", repository)
        + "    with:\n      site-dir: site\n"
    )
    _git(root, "add", workspace.WORKFLOW_FILE)
    _git(root, "commit", "-q", "-m", "Use a fork for the subfolder site")
    site = root / "site"
    site.mkdir()
    assert workspace.workflow_root(site) == root
    assert workspace.selected_source(site) == (repository, "v0.115.0")
    result = _run(site, "0.116.0", monkeypatch)
    assert result.exit_code == 0, result.output
    assert workspace.selected_source(site) == (repository, "v0.116.0")
    assert not (site / ".github").exists()


@pytest.mark.parametrize("unrelated", UNRELATED_SITE_INPUTS)
@pytest.mark.parametrize("command", ["sync", "bump-pin"])
def test_unrelated_site_input_never_selects_root_workflow(
    project, monkeypatch, unrelated, command
):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    original = (workflow.read_text() + unrelated).encode()
    workflow.write_bytes(original)
    site = root / "site"
    site.mkdir()
    monkeypatch.setattr(workspace_versions, "installed", lambda: "0.116.0")
    monkeypatch.setattr(
        workspace, "load_asset", lambda *_: pytest.fail("must not fetch root rules")
    )
    head = _git(root, "rev-parse", "HEAD")
    result = CliRunner().invoke(
        cli, ["workspace", command, "--project", str(site)], catch_exceptions=False
    )
    assert result.exit_code != 0
    assert f"Missing {site / workspace.WORKFLOW_FILE}" in result.output
    assert workflow.read_bytes() == original
    assert _git(root, "rev-parse", "HEAD") == head
    assert not (site / ".github").exists()


@pytest.mark.parametrize("unrelated", UNRELATED_SITE_INPUTS)
def test_unrelated_site_input_preserves_local_workflow_fallback(project, unrelated):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    workflow.write_text(workflow.read_text() + unrelated)
    site = root / "site"
    local = site / workspace.WORKFLOW_FILE
    local.parent.mkdir(parents=True)
    local.write_text(STUB.format(ref="v0.113.0"))
    assert workspace.workflow_root(site) == site
    assert workspace.selected_source(site)[1] == "v0.113.0"


def test_root_workflow_with_unrelated_jobs_still_publishes_site(project, monkeypatch):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    workflow.write_text(
        workflow.read_text()
        + "    with:\n      site-dir: site\n"
        + "  check:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n"
    )
    _git(root, "add", workspace.WORKFLOW_FILE)
    _git(root, "commit", "-q", "-m", "Add site and check job")
    site = root / "site"
    site.mkdir()
    result = _run(site, "0.116.0", monkeypatch)
    assert result.exit_code == 0, result.output
    assert "workspace-quarto-site.yml@v0.116.0" in workflow.read_text()
    assert not (site / ".github").exists()


@pytest.mark.parametrize(
    "unrelated",
    UNRELATED_SITE_INPUTS
    + [
        "  check:\n    runs-on: ubuntu-latest\n    steps:\n      - run: |\n"
        f"          uses: allenai/asta-plugins{workspace.WORKFLOW}v0.115.0\n",
        f"env:\n  EXAMPLE: allenai/asta-plugins{workspace.WORKFLOW}v0.115.0\n",
        "  check:\n    runs-on: ubuntu-latest\n    steps:\n"
        f"      - uses: allenai/asta-plugins{workspace.WORKFLOW}v0.115.0\n"
        "        with:\n          site-dir: other\n",
    ],
)
@pytest.mark.parametrize("command", ["sync", "bump-pin"])
def test_matching_root_ignores_unrelated_inputs_and_source_text(
    project, monkeypatch, unrelated, command
):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    text = workflow.read_text() + "    with:\n      site-dir: site\n" + unrelated
    workflow.write_text(text)
    _git(root, "add", workspace.WORKFLOW_FILE)
    _git(root, "commit", "-q", "-m", "Add site and unrelated YAML")
    site = root / "site"
    site.mkdir()
    (site / ".gitignore").write_text(".asta/cache/\n")
    for name in workspace.UNATTENDED_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(workspace_versions, "installed", lambda: "0.116.0")
    monkeypatch.setattr(workspace, "load_asset", lambda *_: (b"rule\n", _archive({})))
    assert workspace.workflow_root(site) == root
    assert workspace.selected_source(site) == ("allenai/asta-plugins", "v0.115.0")
    result = CliRunner().invoke(
        cli, ["workspace", command, "--project", str(site)], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    assert workflow.read_text() == text.replace("@v0.115.0", "@v0.116.0", 1)
    assert not (site / ".github").exists()
    if command == "bump-pin":
        assert (
            _git(root, "show", "HEAD:" + workspace.WORKFLOW_FILE)
            == workflow.read_text()
        )
    else:
        assert (site / ".asta/cache/workspace.mk").is_file()


@pytest.mark.parametrize("style", ["", "|-", ">-"])
@pytest.mark.parametrize("ref", ["v0.115.0", "${{ inputs.ref }}"])
@pytest.mark.parametrize("local_fallback", [False, True])
@pytest.mark.parametrize("command", ["sync", "bump-pin"])
def test_multiline_workspace_source_errors_instead_of_using_fallback(
    project, monkeypatch, style, ref, local_fallback, command
):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    text = (
        "jobs:\n  docs:\n"
        f"    uses: {style}\n"
        f"      allenai/asta-plugins{workspace.WORKFLOW}{ref}\n"
        "    with:\n      site-dir: site\n"
    )
    workflow.write_text(text)
    site = root / "site"
    site.mkdir()
    local = site / workspace.WORKFLOW_FILE
    if local_fallback:
        local.parent.mkdir(parents=True)
        local.write_text(STUB.format(ref="v0.113.0"))
    monkeypatch.setattr(workspace_versions, "installed", lambda: "0.116.0")
    monkeypatch.setattr(
        workspace, "load_asset", lambda *_: pytest.fail("must reject before fetch")
    )
    head = _git(root, "rev-parse", "HEAD")
    assert workspace.workflow_root(site) == root
    result = CliRunner().invoke(
        cli, ["workspace", command, "--project", str(site)], catch_exceptions=False
    )
    assert result.exit_code != 0
    assert f"Invalid asta-plugins workflow line in {workflow}" in result.output
    assert "on one line" in result.output
    assert workflow.read_text() == text
    assert _git(root, "rev-parse", "HEAD") == head
    if local_fallback:
        assert local.read_text() == STUB.format(ref="v0.113.0")
    else:
        assert not (site / ".github").exists()


@pytest.mark.parametrize(
    "relative", [".github", ".github/workflows", workspace.WORKFLOW_FILE]
)
@pytest.mark.parametrize("command", ["sync", "bump-pin"])
def test_subfolder_rejects_symlinked_root_before_reading(
    project, monkeypatch, tmp_path_factory, relative, command
):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    workflow.write_text(workflow.read_text() + "    with:\n      site-dir: site\n")
    original = workflow.read_bytes()
    site = root / "site"
    site.mkdir()
    linked = root / relative
    external = tmp_path_factory.mktemp("external") / "target"
    linked.rename(external)
    linked.symlink_to(external, target_is_directory=external.is_dir())
    read_text = Path.read_text

    def read(path, *args, **kwargs):
        assert path != workflow, "must reject before reading the symlink target"
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(workspace_versions, "installed", lambda: "0.116.0")
    monkeypatch.setattr(
        workspace, "load_asset", lambda *_: pytest.fail("must reject before fetch")
    )
    result = CliRunner().invoke(
        cli, ["workspace", command, "--project", str(site)], catch_exceptions=False
    )
    assert result.exit_code != 0
    assert "must not contain symlinks" in result.output
    assert workflow.read_bytes() == original
    assert not (site / ".github").exists()


@pytest.mark.parametrize(
    "text",
    [
        STUB.format(ref="v0.115.0")
        + "    with:\n      site-dir: site\n"
        + "  docs:\n    runs-on: ubuntu-latest\n",
        STUB.format(ref="v0.115.0")
        + "    with:\n      site-dir: site\n"
        + "    uses: example/custom/.github/workflows/site.yml@main\n",
        STUB.format(ref="v0.115.0")
        + "    with:\n      site-dir: site\n    with:\n      ignored: true\n",
        STUB.format(ref="v0.115.0")
        + "    with:\n      site-dir: site\n      site-dir: other\n",
        STUB.format(ref="v0.115.0") + "    with:\n      site-dir: site\njobs: {}\n",
    ],
)
def test_duplicate_root_workflow_keys_are_rejected(project, text):
    root = project("v0.115.0")
    (root / workspace.WORKFLOW_FILE).write_text(text)
    with pytest.raises(click.ClickException, match="Duplicate"):
        workspace.workflow_root(root / "site")


def test_invalid_root_yaml_reports_a_click_error(project, monkeypatch):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    workflow.write_text(
        workflow.read_text() + "    with:\n      site-dir: site\n    invalid: [\n"
    )
    (root / "site").mkdir()
    result = _run(root / "site", "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "Invalid YAML" in result.output


def test_unrelated_malformed_root_workflow_keeps_local_fallback(project):
    root = project("v0.115.0")
    (root / workspace.WORKFLOW_FILE).write_text("unrelated: [\n")
    site = root / "site"
    local = site / workspace.WORKFLOW_FILE
    local.parent.mkdir(parents=True)
    local.write_text(STUB.format(ref="v0.113.0"))
    assert workspace.selected_source(site)[1] == "v0.113.0"


@pytest.mark.parametrize("unrelated", UNRELATED_SITE_INPUTS)
@pytest.mark.parametrize("command", ["sync", "bump-pin"])
def test_truncated_root_uses_job_context_for_local_fallback(
    project, monkeypatch, unrelated, command
):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    original = STUB.format(ref="v0.115.0") + unrelated + "broken: [\n"
    workflow.write_text(original)
    site = root / "site"
    local = site / workspace.WORKFLOW_FILE
    local.parent.mkdir(parents=True)
    local.write_text(STUB.format(ref="v0.115.0"))
    (site / ".gitignore").write_text(".asta/cache/\n")
    _git(root, "add", workspace.WORKFLOW_FILE, "site")
    _git(root, "commit", "-q", "-m", "Local site with unrelated truncated root")
    for name in workspace.UNATTENDED_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(workspace_versions, "installed", lambda: "0.116.0")
    monkeypatch.setattr(workspace, "load_asset", lambda *_: (b"rules", _archive({})))
    assert workspace.selected_source(site) == ("allenai/asta-plugins", "v0.115.0")
    result = CliRunner().invoke(
        cli, ["workspace", command, "--project", str(site)], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    assert "@v0.116.0" in local.read_text()
    assert workflow.read_text() == original


@pytest.mark.parametrize(
    "text",
    [
        "env:\n  SITE: &path site\n"
        + STUB.format(ref="v0.115.0")
        + "    with:\n      site-dir: *path\nbroken: [\n",
        "env:\n  INPUTS: &inputs {site-dir: site}\n"
        + STUB.format(ref="v0.115.0")
        + "    with: *inputs\nbroken: [\n",
        "env:\n  JOB: &job\n"
        f"    uses: allenai/asta-plugins{workspace.WORKFLOW}v0.115.0\n"
        "    with: {site-dir: site}\njobs:\n  docs: *job\nbroken: [\n",
        # An error before a matching job leaves its meaning unknown. Do not
        # silently choose the local workflow just because no job was parsed.
        "broken: [\n"
        + STUB.format(ref="v0.115.0")
        + "    with:\n      site-dir: site\n",
        STUB.format(ref="v0.115.0") + "    with: {site-dir: site}\nbroken: [\n",
    ],
    ids=["site-alias", "inputs-alias", "job-alias", "unparsed-job", "flow-input"],
)
@pytest.mark.parametrize("command", ["sync", "bump-pin"])
def test_malformed_root_cannot_hide_selection_behind_local_fallback(
    project, monkeypatch, text, command
):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    workflow.write_text(text)
    site = root / "site"
    local = site / workspace.WORKFLOW_FILE
    local.parent.mkdir(parents=True)
    local_original = STUB.format(ref="v0.115.0")
    local.write_text(local_original)
    _git(root, "add", workspace.WORKFLOW_FILE, "site")
    _git(root, "commit", "-q", "-m", "Malformed root with local fallback")
    head = _git(root, "rev-parse", "HEAD")
    monkeypatch.setattr(workspace_versions, "installed", lambda: "0.116.0")
    monkeypatch.setattr(
        workspace, "load_asset", lambda *_: pytest.fail("must reject before fetch")
    )
    result = CliRunner().invoke(
        cli, ["workspace", command, "--project", str(site)], catch_exceptions=False
    )
    assert result.exit_code != 0
    assert f"Invalid YAML in {workflow}" in result.output
    assert workflow.read_text() == text
    assert local.read_text() == local_original
    assert _git(root, "rev-parse", "HEAD") == head
    assert not (site / ".asta").exists()


@pytest.mark.parametrize("command", ["sync", "bump-pin"])
@pytest.mark.parametrize("local_fallback", [False, True])
@pytest.mark.parametrize("error", [PermissionError("denied"), OSError("read failed")])
def test_root_read_errors_never_select_local_workflow(
    project, monkeypatch, command, local_fallback, error
):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    workflow.write_text(workflow.read_text() + "    with:\n      site-dir: site\n")
    site = root / "site"
    site.mkdir()
    local = site / workspace.WORKFLOW_FILE
    if local_fallback:
        local.parent.mkdir(parents=True)
        local.write_text(STUB.format(ref="v0.115.0"))
    _git(root, "add", workspace.WORKFLOW_FILE, "site")
    _git(root, "commit", "-q", "-m", "Root publishes subfolder site")
    head = _git(root, "rev-parse", "HEAD")
    original = workflow.read_bytes()
    read_text = Path.read_text

    def read(path, *args, **kwargs):
        if path == workflow:
            raise error
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(workspace_versions, "installed", lambda: "0.116.0")
    monkeypatch.setattr(
        workspace, "load_asset", lambda *_: pytest.fail("must reject before fetch")
    )
    result = CliRunner().invoke(
        cli, ["workspace", command, "--project", str(site)], catch_exceptions=False
    )
    assert result.exit_code != 0
    assert f"Could not read {workflow}: {error}" in result.output
    assert workflow.read_bytes() == original
    assert _git(root, "rev-parse", "HEAD") == head
    if local_fallback:
        assert local.read_text() == STUB.format(ref="v0.115.0")
    else:
        assert not (site / ".github").exists()
    assert not (site / ".asta").exists()


@pytest.mark.parametrize("command", ["sync", "bump-pin"])
def test_non_utf8_root_never_selects_local_workflow(project, monkeypatch, command):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    original = workflow.read_bytes() + b"    with:\n      site-dir: site\n# \xff\n"
    workflow.write_bytes(original)
    site = root / "site"
    local = site / workspace.WORKFLOW_FILE
    local.parent.mkdir(parents=True)
    local.write_text(STUB.format(ref="v0.115.0"))
    result = CliRunner().invoke(
        cli, ["workspace", command, "--project", str(site)], catch_exceptions=False
    )
    assert result.exit_code != 0
    assert f"Workflow must be UTF-8: {workflow}" in result.output
    assert workflow.read_bytes() == original
    assert local.read_text() == STUB.format(ref="v0.115.0")
    assert not (site / ".asta").exists()


@pytest.mark.parametrize("failure", ["permission", "invalid-yaml"])
def test_offline_selection_error_preserves_local_cache(project, monkeypatch, failure):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    workflow.write_text(
        "env:\n  SITE: &path site\n"
        + STUB.format(ref="v0.115.0")
        + "    with:\n      site-dir: *path\n"
        + ("broken: [\n" if failure == "invalid-yaml" else "")
    )
    site = root / "site"
    local = site / workspace.WORKFLOW_FILE
    local.parent.mkdir(parents=True)
    local.write_text(STUB.format(ref="v0.115.0"))
    cache = site / ".asta/cache"
    cache.mkdir(parents=True)
    originals = {workflow: workflow.read_bytes(), local: local.read_bytes()}
    for name in ("workspace.mk", "workspace.json"):
        path = cache / name
        path.write_text(f"cached {name}\n")
        originals[path] = path.read_bytes()
    read_text = Path.read_text

    def read(path, *args, **kwargs):
        if failure == "permission" and path == workflow:
            raise PermissionError("denied")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(
        workspace, "load_asset", lambda *_: pytest.fail("offline check must not fetch")
    )
    result = CliRunner().invoke(
        cli,
        ["workspace", "sync", "--check-selection", "--project", str(site)],
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    expected = "Could not read" if failure == "permission" else "Invalid YAML in"
    assert f"{expected} {workflow}" in result.output
    assert {path: path.read_bytes() for path in originals} == originals


@pytest.mark.parametrize("command", ["sync", "bump-pin"])
def test_missing_root_workflow_preserves_local_fallback(project, monkeypatch, command):
    root = project("v0.115.0")
    (root / workspace.WORKFLOW_FILE).unlink()
    site = root / "site"
    local = site / workspace.WORKFLOW_FILE
    local.parent.mkdir(parents=True)
    local.write_text(STUB.format(ref="v0.115.0"))
    (site / ".gitignore").write_text(".asta/cache/\n")
    _git(root, "add", workspace.WORKFLOW_FILE, "site")
    _git(root, "commit", "-q", "-m", "Use only a local site workflow")
    for name in workspace.UNATTENDED_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(workspace_versions, "installed", lambda: "0.116.0")
    monkeypatch.setattr(workspace, "load_asset", lambda *_: (b"rules", _archive({})))
    assert workspace.workflow_root(site) == site
    result = CliRunner().invoke(
        cli, ["workspace", command, "--project", str(site)], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    assert "@v0.116.0" in local.read_text()
    assert not (root / workspace.WORKFLOW_FILE).exists()


@pytest.mark.parametrize(
    "relative", [".github", ".github/workflows", workspace.WORKFLOW_FILE]
)
@pytest.mark.parametrize("command", ["sync", "bump-pin"])
def test_symlinked_root_preserves_valid_local_workflow(
    project, monkeypatch, tmp_path_factory, relative, command
):
    root = project("v0.115.0")
    root_workflow = root / workspace.WORKFLOW_FILE
    linked = root / relative
    external = tmp_path_factory.mktemp("external") / "target"
    linked.rename(external)
    linked.symlink_to(external, target_is_directory=external.is_dir())
    site = root / "site"
    local = site / workspace.WORKFLOW_FILE
    local.parent.mkdir(parents=True)
    local.write_text(STUB.format(ref="v0.115.0"))
    (site / ".gitignore").write_text(".asta/cache/\n")
    _git(root, "add", "site")
    _git(root, "commit", "-q", "-m", "Local workspace")
    original = root_workflow.read_bytes()
    read_text = Path.read_text

    def read(path, *args, **kwargs):
        assert path != root_workflow, "root symlink must not be read"
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    for name in workspace.UNATTENDED_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(workspace_versions, "installed", lambda: "0.116.0")
    monkeypatch.setattr(workspace, "load_asset", lambda *_: (b"rules", _archive({})))
    assert workspace.workflow_root(site) == site
    result = CliRunner().invoke(cli, ["workspace", command, "--project", str(site)])
    assert result.exit_code == 0, result.output
    assert "@v0.116.0" in local.read_text()
    assert root_workflow.read_bytes() == original


@pytest.mark.parametrize(
    ("directory", "value", "prefix"),
    [
        ("site's notes", "site's notes", ""),
        ("site\tnotes", '"site\\tnotes"', ""),
        ("site", "&path site", ""),
        ("site", "*path", "env:\n  SITE: &path site\n"),
        ("site notes", '"site\\x20notes"', ""),
        ("site notes", '"site\\ notes"', ""),
    ],
)
def test_subfolder_uses_yaml_decoded_site_value(
    project, monkeypatch, directory, value, prefix
):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    workflow.write_text(
        prefix + STUB.format(ref="v0.115.0") + f"    with:\n      site-dir: {value}\n"
    )
    _git(root, "add", workspace.WORKFLOW_FILE)
    _git(root, "commit", "-q", "-m", "Site scalar")
    site = root / directory
    site.mkdir()
    assert workspace.workflow_root(site) == root
    result = _run(site, "0.116.0", monkeypatch)
    assert result.exit_code == 0, result.output
    assert f"site-dir: {value}\n" in workflow.read_text()
    assert "@v0.116.0" in workflow.read_text()


@pytest.mark.parametrize("character", ["\v", "\f", "\x1c", "\x1d", "\x1e"])
def test_yaml_rejects_extra_splitlines_characters_before_pin_edit(
    project, monkeypatch, character
):
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    original = ("# comment" + character + "\n" + STUB.format(ref="v0.115.0")).encode()
    workflow.write_bytes(original)
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "Invalid YAML" in result.output
    assert workflow.read_bytes() == original
