"""Workspace asset sync uses the project's workflow version."""

import io
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from asta.cli import cli
from asta.commands import workspace as workspace_module


def project_with_ref(
    tmp_path: Path, ref: str, repository: str = "allenai/asta-plugins"
) -> Path:
    project = tmp_path / "project"
    workflow = project / ".github/workflows/docs.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n  docs:\n"
        f"    uses: {repository}/.github/workflows/workspace-quarto-site.yml@{ref}\n"
    )
    return project


def test_sync_uses_workflow_ref_and_refreshes_only_when_requested(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "main")
    calls = []

    def fetch(repository, ref):
        calls.append((repository, ref))
        return f"rule-{len(calls)}".encode(), f"archive-{len(calls)}".encode()

    monkeypatch.setattr(workspace_module, "load_asset", fetch)
    runner = CliRunner()
    args = ["workspace", "sync", "--project", str(project)]
    assert runner.invoke(cli, args).exit_code == 0
    assert runner.invoke(cli, args).exit_code == 0
    assert calls == [("allenai/asta-plugins", "main")]
    assert runner.invoke(cli, args + ["--refresh"]).exit_code == 0
    assert calls == [("allenai/asta-plugins", "main")] * 2
    cached_rules = (project / ".asta/cache/workspace.mk").read_bytes()
    assert cached_rules.endswith(b"rule-2")
    assert b"override ASTA_PLUGINS_REF := main\n" in cached_rules
    assert b"override ASTA_WORKSPACE_ARCHIVE := .asta/cache/archives/" in cached_rules
    assert (project / ".asta/cache/workspace.mk").stat().st_mode & 0o777 == 0o644
    assert len(list((project / ".asta/cache/archives").iterdir())) == 2

    workflow = project / ".github/workflows/docs.yml"
    workflow.write_text(workflow.read_text().replace("@main", "@v0.105.0"))
    assert runner.invoke(cli, args).exit_code == 0
    assert calls[-1] == ("allenai/asta-plugins", "v0.105.0")


def test_sync_uses_resolved_workflow_sha_in_ci(tmp_path: Path, monkeypatch) -> None:
    project = project_with_ref(tmp_path, "main")
    calls = []

    def fetch(repository, ref):
        calls.append((repository, ref))
        return b"rule", b"archive"

    monkeypatch.setattr(workspace_module, "load_asset", fetch)
    runner = CliRunner()
    args = ["workspace", "sync", "--project", str(project)]
    monkeypatch.setenv("ASTA_WORKSPACE_RESOLVED_SHA", "a" * 40)
    assert runner.invoke(cli, args).exit_code == 0
    monkeypatch.setenv("ASTA_WORKSPACE_RESOLVED_SHA", "b" * 40)
    assert runner.invoke(cli, args).exit_code == 0
    assert calls == [
        ("allenai/asta-plugins", "a" * 40),
        ("allenai/asta-plugins", "b" * 40),
    ]


def test_sync_uses_called_workflow_repository_in_ci(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "main", "example/asta-plugins")
    calls = []

    def fetch(repository, ref):
        calls.append((repository, ref))
        return b"rule", b"archive"

    monkeypatch.setattr(workspace_module, "load_asset", fetch)
    monkeypatch.setenv("ASTA_WORKSPACE_RESOLVED_SHA", "a" * 40)
    monkeypatch.setenv("ASTA_WORKSPACE_RESOLVED_REPOSITORY", "example/asta-plugins")
    args = ["workspace", "sync", "--project", str(project)]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert calls == [("example/asta-plugins", "a" * 40)]
    workflow = project / ".github/workflows/docs.yml"
    workflow.write_text(workflow.read_text().replace("example/", "Example/"))
    assert CliRunner().invoke(cli, args).exit_code == 0
    assert calls == [("example/asta-plugins", "a" * 40)]
    monkeypatch.setenv("ASTA_WORKSPACE_RESOLVED_REPOSITORY", "allenai/asta-plugins")
    assert CliRunner().invoke(cli, args).exit_code != 0


def test_moving_ref_uses_tag_before_branch_and_fetches_commit(monkeypatch) -> None:
    def refs(*args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=(f"{'a' * 40}\trefs/heads/latest\n{'b' * 40}\trefs/tags/latest\n"),
        )

    monkeypatch.setattr(workspace_module.subprocess, "run", refs)
    assert workspace_module.archive_url("allenai/asta-plugins", "latest") == (
        f"https://github.com/allenai/asta-plugins/archive/{'b' * 40}.tar.gz"
    )


def test_other_branch_ref_resolves_to_commit(monkeypatch) -> None:
    def refs(*args, **kwargs):
        return subprocess.CompletedProcess(
            args, 0, stdout=f"{'c' * 40}\trefs/heads/feature/paper\n"
        )

    monkeypatch.setattr(workspace_module.subprocess, "run", refs)
    assert workspace_module.archive_url("allenai/asta-plugins", "feature/paper") == (
        f"https://github.com/allenai/asta-plugins/archive/{'c' * 40}.tar.gz"
    )


def test_version_shaped_branch_without_tag_resolves_to_commit(monkeypatch) -> None:
    def refs(*args, **kwargs):
        return subprocess.CompletedProcess(
            args, 0, stdout=f"{'c' * 40}\trefs/heads/v1.2.3\n"
        )

    monkeypatch.setattr(workspace_module.subprocess, "run", refs)
    assert workspace_module.archive_url("allenai/asta-plugins", "v1.2.3") == (
        f"https://github.com/allenai/asta-plugins/archive/{'c' * 40}.tar.gz"
    )


def test_sync_replaces_corrupt_cached_archive(tmp_path: Path, monkeypatch) -> None:
    project = project_with_ref(tmp_path, "main")
    calls = []

    def fetch(repository, ref):
        calls.append((repository, ref))
        return b"rule", b"archive"

    monkeypatch.setattr(workspace_module, "load_asset", fetch)
    args = ["workspace", "sync", "--project", str(project)]
    runner = CliRunner()
    assert runner.invoke(cli, args).exit_code == 0
    archive_path = next((project / ".asta/cache/archives").iterdir())
    archive_path.write_bytes(b"corrupt")

    result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert calls == [("allenai/asta-plugins", "main")] * 2
    assert archive_path.read_bytes() == b"archive"


def test_sync_keeps_local_override_and_never_fetches(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "main")
    (project / "workspace.mk").write_text("local")
    monkeypatch.setattr(
        workspace_module,
        "load_asset",
        lambda repository, ref: (_ for _ in ()).throw(
            AssertionError("unexpected fetch")
        ),
    )
    result = CliRunner().invoke(cli, ["workspace", "sync", "--project", str(project)])
    assert result.exit_code == 0
    assert (project / "workspace.mk").read_text() == "local"
    assert not (project / ".asta/cache/workspace.mk").exists()


def test_sync_offline_uses_only_matching_verified_cache(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "main")
    runner = CliRunner()
    args = ["workspace", "sync", "--project", str(project)]
    monkeypatch.setattr(
        workspace_module, "load_asset", lambda repository, ref: (b"cached", b"archive")
    )
    assert runner.invoke(cli, args).exit_code == 0

    def fail(repository, ref):
        raise workspace_module.click.ClickException("offline")

    monkeypatch.setattr(workspace_module, "load_asset", fail)
    assert runner.invoke(cli, args + ["--refresh"]).exit_code == 0
    workflow = project / ".github/workflows/docs.yml"
    workflow.write_text(workflow.read_text().replace("@main", "@latest"))
    assert runner.invoke(cli, args).exit_code != 0
    assert (project / ".asta/cache/workspace.mk").read_bytes().endswith(b"cached")


def test_sync_rejects_invalid_ref(tmp_path: Path) -> None:
    project = project_with_ref(tmp_path, "../../other")
    result = CliRunner().invoke(cli, ["workspace", "sync", "--project", str(project)])
    assert result.exit_code != 0
    assert "Invalid asta-plugins" in result.output


def test_sync_reads_quoted_ref_with_comment(tmp_path: Path, monkeypatch) -> None:
    project = project_with_ref(tmp_path, "main")
    workflow = project / ".github/workflows/docs.yml"
    workflow.write_text(
        workflow.read_text()
        .replace("@main", "@main' # canary")
        .replace("uses: allenai", "uses: 'allenai")
    )
    monkeypatch.setattr(
        workspace_module,
        "load_asset",
        lambda repository, ref: (ref.encode(), b"archive"),
    )
    result = CliRunner().invoke(cli, ["workspace", "sync", "--project", str(project)])
    assert result.exit_code == 0, result.output
    assert (project / ".asta/cache/workspace.mk").read_bytes().endswith(b"main")


def test_sync_rejects_mismatched_quotes(tmp_path: Path) -> None:
    project = project_with_ref(tmp_path, "main")
    workflow = project / ".github/workflows/docs.yml"
    workflow.write_text(workflow.read_text().replace("@main", "@main'"))
    result = CliRunner().invoke(cli, ["workspace", "sync", "--project", str(project)])
    assert result.exit_code != 0


def test_sync_recovers_from_non_object_manifest(tmp_path: Path, monkeypatch) -> None:
    project = project_with_ref(tmp_path, "main")
    cache = project / ".asta/cache"
    cache.mkdir(parents=True)
    (cache / "workspace.json").write_text("[]")
    monkeypatch.setattr(
        workspace_module, "load_asset", lambda repository, ref: (b"rule", b"archive")
    )
    result = CliRunner().invoke(cli, ["workspace", "sync", "--project", str(project)])
    assert result.exit_code == 0, result.output


def test_cached_sync_updates_target_mtime(tmp_path: Path, monkeypatch) -> None:
    project = project_with_ref(tmp_path, "main")
    monkeypatch.setattr(
        workspace_module, "load_asset", lambda repository, ref: (b"rule", b"archive")
    )
    args = ["workspace", "sync", "--project", str(project)]
    runner = CliRunner()
    assert runner.invoke(cli, args).exit_code == 0
    target = project / ".asta/cache/workspace.mk"
    old = time.time() - 60
    os.utime(target, (old, old))
    assert runner.invoke(cli, args).exit_code == 0
    assert target.stat().st_mtime > old


def test_sync_requires_ignored_cache_in_git_project(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "main")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    monkeypatch.setattr(
        workspace_module, "load_asset", lambda repository, ref: (b"shared", b"archive")
    )
    args = ["workspace", "sync", "--project", str(project)]
    runner = CliRunner()
    result = runner.invoke(cli, args)
    assert result.exit_code != 0
    assert "Add .asta/cache/" in result.output
    (project / ".gitignore").write_text(".asta/cache/\n")
    assert runner.invoke(cli, args).exit_code == 0


def test_thin_makefile_bootstraps_managed_targets(tmp_path: Path) -> None:
    if shutil.which("make") is None:
        pytest.skip("make not installed")
    project = project_with_ref(tmp_path, "main")
    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets/Makefile.managed"
    )
    (project / "Makefile").write_text(source.read_text())
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()
    fake_cli = tool_dir / "asta"
    fake_cli.write_text(
        "#!/bin/sh\n"
        "mkdir -p .asta/cache\n"
        "printf 'preview:\\n\\t@echo managed-preview\\n' > .asta/cache/workspace.mk\n"
    )
    fake_cli.chmod(0o755)
    result = subprocess.run(
        ["make", "preview"],
        cwd=project,
        env={**os.environ, "PATH": str(tool_dir) + os.pathsep + os.environ["PATH"]},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "managed-preview" in result.stdout


def test_thin_makefile_rejects_ref_override(tmp_path: Path) -> None:
    if shutil.which("make") is None:
        pytest.skip("make not installed")
    project = project_with_ref(tmp_path, "main")
    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets/Makefile.managed"
    )
    (project / "Makefile").write_text(source.read_text())
    env = {**os.environ, "ASTA_PLUGINS_REF": "v0.104.1"}
    commands = (
        (["make", "preview"], env),
        (["make", "preview", "ASTA_PLUGINS_REF=v0.104.1"], os.environ),
    )
    for command, variables in commands:
        result = subprocess.run(
            command, cwd=project, env=variables, text=True, capture_output=True
        )
        assert result.returncode != 0
        assert "ASTA_PLUGINS_REF cannot select managed rules" in result.stderr

    (project / "workspace.mk").write_text("preview:\n\t@echo customized\n")
    result = subprocess.run(
        ["make", "preview"], cwd=project, env=env, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert "customized" in result.stdout


def test_full_and_managed_makefiles_share_their_build_recipes() -> None:
    assets = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets"
    )

    def recipe(source: str, target: str) -> str:
        lines = source.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
        commands = []
        for line in lines[start + 1 :]:
            if line.startswith("\t"):
                commands.append(line)
            elif commands:
                break
        return "\n".join(commands)

    full = (assets / "Makefile").read_text()
    managed = (assets / "workspace.mk").read_text()
    for target in (
        "preview",
        "render",
        "clean",
        "dev",
        "deployed-url",
        "preview-baseline",
        "preview-ready",
    ):
        assert recipe(full, target) == recipe(managed, target), target
    assert recipe(full, "check") == recipe(managed, "workspace-shared-check")
    assert "ASTA_WORKSPACE_ARCHIVE" in recipe(managed, "workspace-assets")
    assert "ASTA_WORKSPACE_ARCHIVE" not in recipe(full, "workspace-assets")


def test_shared_workflow_installs_cli_from_its_own_commit_for_managed_projects() -> (
    None
):
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/workspace-quarto-site.yml"
    ).read_text()
    assert "Install Asta CLI for managed workspace rules" in workflow
    assert "job.workflow_sha" in workflow
    assert "ASTA_WORKSPACE_RESOLVED_SHA: ${{ job.workflow_sha }}" in workflow
    assert (
        "ASTA_WORKSPACE_RESOLVED_REPOSITORY: ${{ job.workflow_repository }}" in workflow
    )
    assert "git+https://github.com/${{ job.workflow_repository }}.git@" in workflow


def test_archive_reader_accepts_only_the_expected_regular_file(monkeypatch) -> None:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
        payload = b"check:\n\t@true\n"
        entry = tarfile.TarInfo("asta-plugins-test/" + workspace_module.ASSET)
        entry.size = len(payload)
        bundle.addfile(entry, io.BytesIO(payload))
        nested = tarfile.TarInfo("asta-plugins-test/fixture/" + workspace_module.ASSET)
        nested.size = len(payload)
        bundle.addfile(nested, io.BytesIO(payload))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, *_):
            return archive.getvalue()

    monkeypatch.setattr(
        workspace_module, "urlopen", lambda *_args, **_kwargs: Response()
    )
    assert workspace_module.load_asset("allenai/asta-plugins", "a" * 40) == (
        payload,
        archive.getvalue(),
    )


def test_archive_reader_wraps_incomplete_http_response(monkeypatch) -> None:
    def interrupted(*args, **kwargs):
        raise workspace_module.http.client.IncompleteRead(b"partial")

    monkeypatch.setattr(workspace_module, "urlopen", interrupted)
    with pytest.raises(workspace_module.click.ClickException):
        workspace_module.load_asset("allenai/asta-plugins", "a" * 40)
