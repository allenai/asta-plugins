"""`asta workspace bump-pin` moves a release pin behind asta to its release."""

import subprocess
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from asta.cli import cli
from asta.commands import workspace, workspace_versions

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


def _run(root: Path, version: str, monkeypatch):
    monkeypatch.setattr(workspace_versions, "installed", lambda: version)
    return CliRunner().invoke(
        cli, ["workspace", "bump-pin", "--project", str(root)], catch_exceptions=False
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
    result = CliRunner().invoke(cli, ["workspace", "bump-pin", "--project", str(root)])
    assert result.exit_code != 0
    assert "uncommitted changes" in result.output
    assert _git(root, "rev-parse", "HEAD") == head


def test_non_git_project_is_unchanged(tmp_path, monkeypatch) -> None:
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
    project, tmp_path, monkeypatch, relative
) -> None:
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    original = workflow.read_bytes()
    linked = root / relative
    external = tmp_path.parent / (tmp_path.name + "-external")
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


def test_rejected_commit_restores_workflow_and_preserves_other_work(
    project, monkeypatch
) -> None:
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
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
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "commit rejected" in result.output
    assert workflow.read_bytes() == original
    assert _git(root, "rev-parse", "HEAD") == head
    assert _git(root, "diff", "--cached") == staged
    assert notes.read_text() == "unstaged work\n"


def test_failed_validation_restores_workflow(project, monkeypatch) -> None:
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    original = workflow.read_bytes()
    selected_source = workspace.selected_source

    def validate(project):
        if b"@v0.116.0" in workflow.read_bytes():
            raise click.ClickException("validation failed")
        return selected_source(project)

    monkeypatch.setattr(workspace, "selected_source", validate)
    result = _run(root, "0.116.0", monkeypatch)
    assert result.exit_code != 0
    assert "validation failed" in result.output
    assert workflow.read_bytes() == original
    assert not _git(root, "status", "--porcelain")


def test_partial_write_failure_restores_workflow(project, monkeypatch) -> None:
    root = project("v0.115.0")
    workflow = root / workspace.WORKFLOW_FILE
    original = workflow.read_bytes()
    write_bytes = Path.write_bytes

    def write(path, data):
        if path == workflow and data != original:
            write_bytes(path, b"partial")
            raise OSError("write failed")
        return write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", write)
    result = CliRunner().invoke(cli, ["workspace", "bump-pin", "--project", str(root)])
    assert result.exit_code != 0
    assert workflow.read_bytes() == original
    assert not _git(root, "status", "--porcelain")
