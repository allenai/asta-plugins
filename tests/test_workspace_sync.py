"""Workspace asset sync uses the project's workflow version."""

import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
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
        return f"rule-{len(calls)}".encode(), _archive(
            {"revision": str(len(calls)).encode()}
        )

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
        return b"rule", _archive({})

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
        return b"rule", _archive({})

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


def test_cached_version_shaped_branch_prompts_refresh(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "v1.2.3")
    monkeypatch.setattr(
        workspace_module,
        "load_asset",
        lambda *_args: (b"rules", _archive({})),
    )
    args = ["workspace", "sync", "--project", str(project)]
    runner = CliRunner()
    assert runner.invoke(cli, args).exit_code == 0
    cached = runner.invoke(cli, args)
    assert cached.exit_code == 0
    assert "run 'asta workspace sync --refresh' to update" in cached.output


def test_sync_replaces_corrupt_cached_archive(tmp_path: Path, monkeypatch) -> None:
    project = project_with_ref(tmp_path, "main")
    calls = []

    def fetch(repository, ref):
        calls.append((repository, ref))
        return b"rule", _archive({})

    monkeypatch.setattr(workspace_module, "load_asset", fetch)
    args = ["workspace", "sync", "--project", str(project)]
    runner = CliRunner()
    assert runner.invoke(cli, args).exit_code == 0
    archive_path = next((project / ".asta/cache/archives").iterdir())
    archive_path.write_bytes(b"corrupt")

    result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert calls == [("allenai/asta-plugins", "main")] * 2
    assert workspace_module.load_scripts(archive_path.read_bytes()) == {
        name: b"script" for name in workspace_module.SCRIPTS
    }


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
        workspace_module,
        "load_asset",
        lambda repository, ref: (b"cached", _archive({})),
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
        lambda repository, ref: (ref.encode(), _archive({})),
    )
    result = CliRunner().invoke(cli, ["workspace", "sync", "--project", str(project)])
    assert result.exit_code == 0, result.output
    assert (project / ".asta/cache/workspace.mk").read_bytes().endswith(b"main")


def test_multiple_workflow_calls_must_select_one_source(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "main")
    workflow = project / ".github/workflows/docs.yml"
    original = workflow.read_text()
    workflow.write_text(original + original)
    monkeypatch.setattr(
        workspace_module,
        "load_asset",
        lambda *_args: (b"rules", _archive({})),
    )
    args = ["workspace", "sync", "--project", str(project)]
    assert CliRunner().invoke(cli, args).exit_code == 0

    workflow.write_text(original + original.replace("@main", "@latest"))
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert "Expected one asta-plugins workspace source" in result.output


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
        workspace_module, "load_asset", lambda repository, ref: (b"rule", _archive({}))
    )
    result = CliRunner().invoke(cli, ["workspace", "sync", "--project", str(project)])
    assert result.exit_code == 0, result.output


def test_cached_sync_updates_target_mtime(tmp_path: Path, monkeypatch) -> None:
    project = project_with_ref(tmp_path, "main")
    monkeypatch.setattr(
        workspace_module, "load_asset", lambda repository, ref: (b"rule", _archive({}))
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
        workspace_module,
        "load_asset",
        lambda repository, ref: (b"shared", _archive({})),
    )
    args = ["workspace", "sync", "--project", str(project)]
    runner = CliRunner()
    result = runner.invoke(cli, args)
    assert result.exit_code != 0
    assert "Add .asta/cache/" in result.output
    (project / ".gitignore").write_text(".asta/cache/\n")
    assert runner.invoke(cli, args).exit_code == 0


def test_sync_rejects_tracked_cache_even_when_ignore_rule_exists(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "main")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / ".gitignore").write_text(".asta/cache/\n")
    cache = project / ".asta/cache"
    cache.mkdir(parents=True)
    (cache / "workspace.mk").write_text("tracked rules\n")
    subprocess.run(
        ["git", "-C", str(project), "add", "-f", ".asta/cache/workspace.mk"],
        check=True,
    )
    monkeypatch.setattr(
        workspace_module,
        "load_asset",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected fetch")),
    )

    result = CliRunner().invoke(cli, ["workspace", "sync", "--project", str(project)])
    assert result.exit_code != 0
    assert "Workspace cache is tracked by Git" in result.output
    assert "git rm --cached -r .asta/cache" in result.output
    assert (cache / "workspace.mk").read_text() == "tracked rules\n"


def test_atomic_write_cleans_temp_file_after_write_failure(
    tmp_path: Path, monkeypatch
) -> None:
    original = tempfile.NamedTemporaryFile

    class FailingFile:
        def __init__(self, **kwargs):
            self.file = original(**kwargs)
            self.name = self.file.name

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.file.close()

        def write(self, _data):
            raise OSError("disk full")

    monkeypatch.setattr(workspace_module.tempfile, "NamedTemporaryFile", FailingFile)
    with pytest.raises(OSError, match="disk full"):
        workspace_module._atomic_write(tmp_path / "workspace.mk", b"rules")
    assert list(tmp_path.iterdir()) == []


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
        'if [ "$3" = --help ]; then exit 0; fi\n'
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
        assert "unset ASTA_PLUGINS_REF" in result.stderr

    (project / "workspace.mk").write_text("preview:\n\t@echo customized\n")
    result = subprocess.run(
        ["make", "preview"], cwd=project, env=env, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert "customized" in result.stdout


def test_thin_makefile_dev_needs_no_cli(tmp_path: Path) -> None:
    if shutil.which("make") is None:
        pytest.skip("make not installed")
    project = project_with_ref(tmp_path, "main")
    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets/Makefile.managed"
    )
    (project / "Makefile").write_text(source.read_text())
    result = subprocess.run(
        [shutil.which("make"), "-n", "dev"],
        cwd=project,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "vscode-remote://dev-container+" in result.stdout
    assert not (project / ".asta").exists()


def test_thin_makefile_explains_older_cli(tmp_path: Path) -> None:
    make = shutil.which("make")
    if make is None:
        pytest.skip("make not installed")
    project = project_with_ref(tmp_path, "latest")
    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets/Makefile.managed"
    )
    (project / "Makefile").write_text(source.read_text())
    tools = tmp_path / "tools"
    tools.mkdir()
    old_cli = tools / "asta"
    old_cli.write_text("#!/bin/sh\necho 'No such command: workspace' >&2\nexit 2\n")
    old_cli.chmod(0o755)
    result = subprocess.run(
        [make, "preview"],
        cwd=project,
        env={"PATH": str(tools) + ":/usr/bin:/bin"},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "Install the Asta CLI 0.105.0 or newer" in result.stderr
    assert "No such command" not in result.stderr
    assert not (project / ".asta").exists()


@pytest.mark.parametrize(
    "goals", [("catalogue",), ("pull",), ("catalogue", "pull"), ("dev", "catalogue")]
)
def test_thin_makefile_local_goals_need_no_cli(tmp_path: Path, goals) -> None:
    make = shutil.which("make")
    if make is None:
        pytest.skip("make not installed")
    project = tmp_path / "project"
    project.mkdir()
    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets/Makefile.managed"
    )
    (project / "Makefile").write_text(
        "ASTA_WORKSPACE_LOCAL_GOALS := catalogue pull\n"
        + source.read_text()
        + "\ncatalogue pull:\n\t@echo project-only\n"
    )
    result = subprocess.run(
        [make, "-n", *goals],
        cwd=project,
        env={"PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "project-only" in result.stdout
    assert not (project / ".asta").exists()


@pytest.mark.parametrize(
    "goals", [(), ("preview", "catalogue"), ("catalogue", "preview")]
)
def test_thin_makefile_local_goals_do_not_skip_shared_targets(
    tmp_path: Path, goals
) -> None:
    make = shutil.which("make")
    if make is None:
        pytest.skip("make not installed")
    project = project_with_ref(tmp_path, "latest")
    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets/Makefile.managed"
    )
    (project / "Makefile").write_text(
        "ASTA_WORKSPACE_LOCAL_GOALS := catalogue\n"
        + source.read_text()
        + "\ncatalogue:\n\t@echo project-only\n"
    )
    result = subprocess.run(
        [make, *goals],
        cwd=project,
        env={"PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "Install the Asta CLI" in result.stderr


def test_thin_makefile_local_override_precedes_local_goals(tmp_path: Path) -> None:
    make = shutil.which("make")
    if make is None:
        pytest.skip("make not installed")
    project = tmp_path / "project"
    project.mkdir()
    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets/Makefile.managed"
    )
    (project / "Makefile").write_text(
        "ASTA_WORKSPACE_LOCAL_GOALS := catalogue\n" + source.read_text()
    )
    (project / "workspace.mk").write_text("catalogue:\n\t@echo customized\n")
    result = subprocess.run(
        [make, "catalogue"],
        cwd=project,
        env={"PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "customized" in result.stdout
    assert not (project / ".asta").exists()


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
        shared = recipe(managed, target).replace(
            "$(call workspace_script,wait-for-preview.sh)",
            "scripts/wait-for-preview.sh",
        )
        assert recipe(full, target) == shared, target
    thin = (assets / "Makefile.managed").read_text()
    assert recipe(thin, "dev") == recipe(managed, "dev")
    assert recipe(full, "check") == "\tsh scripts/quarto-check.sh"
    assert "workspace_script,quarto-check.sh" in recipe(
        managed, "workspace-shared-check"
    )
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


def test_managed_archive_supplies_evidence_extension(
    tmp_path: Path, monkeypatch
) -> None:
    if shutil.which("make") is None:
        pytest.skip("make not installed")
    project = project_with_ref(tmp_path, "main")
    assets = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets"
    )
    (project / "Makefile").write_text((assets / "Makefile.managed").read_text())
    archive_file = io.BytesIO()
    with tarfile.open(fileobj=archive_file, mode="w:gz") as bundle:
        payload = b"evidence filter\n"
        member = tarfile.TarInfo(
            "asta-plugins-test/plugins/asta-tools/skills/workspace/assets/"
            "_extensions/evidence/snippet.lua"
        )
        member.size = len(payload)
        bundle.addfile(member, io.BytesIO(payload))
    monkeypatch.setattr(
        workspace_module,
        "load_asset",
        lambda *_args: (
            (assets / "workspace.mk").read_bytes(),
            archive_file.getvalue(),
        ),
    )
    result = CliRunner().invoke(cli, ["workspace", "sync", "--project", str(project)])
    assert result.exit_code == 0, result.output

    built = subprocess.run(
        ["make", "workspace-assets"], cwd=project, text=True, capture_output=True
    )
    assert built.returncode == 0, built.stderr
    assert (project / "_extensions/evidence/snippet.lua").read_bytes() == payload


def test_repository_archive_fits_workspace_sync_limits() -> None:
    root = Path(__file__).resolve().parents[1]
    archive = subprocess.run(
        ["git", "archive", "--format=tar.gz", "HEAD"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    assert len(archive) < workspace_module.MAX_ARCHIVE_BYTES
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        members = bundle.getmembers()
    assert len(members) < 10000
    assert (
        sum(member.size for member in members) < workspace_module.MAX_UNCOMPRESSED_BYTES
    )


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


def _archive(files: dict[str, bytes], *, scripts: bool = True) -> bytes:
    if scripts:
        files = {
            **{
                workspace_module.ASSET_DIR + name: b"script"
                for name in workspace_module.SCRIPTS
            },
            **files,
        }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, data in files.items():
            info = tarfile.TarInfo(f"asta-plugins-abc/{name}")
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_sync_caches_managed_scripts_from_archive(tmp_path: Path, monkeypatch) -> None:
    project = project_with_ref(tmp_path, "v0.106.0")
    archive = _archive(
        {
            workspace_module.ASSET_DIR + name: f"echo {name}".encode()
            for name in workspace_module.SCRIPTS
        }
    )
    monkeypatch.setattr(workspace_module, "load_asset", lambda r, f: (b"rule", archive))
    runner = CliRunner()
    args = ["workspace", "sync", "--project", str(project)]
    assert runner.invoke(cli, args).exit_code == 0
    for name in workspace_module.SCRIPTS:
        cached = cached_scripts(project) / name
        assert cached.read_bytes() == f"echo {name}".encode()


@pytest.mark.parametrize("mode", ["fresh", "cached", "offline-refresh"])
def test_require_scripts_allows_removal_only_with_working_managed_targets(
    tmp_path: Path, monkeypatch, mode: str
) -> None:
    make = shutil.which("make")
    if make is None:
        pytest.skip("make not installed")
    project = project_with_ref(tmp_path, "main")
    assets = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets"
    )
    (project / "Makefile").write_text((assets / "Makefile.managed").read_text())
    archive = _archive(
        {
            workspace_module.ASSET_DIR + name: f"echo managed-{name}\n".encode()
            for name in workspace_module.SCRIPTS
        }
    )
    monkeypatch.setattr(
        workspace_module,
        "load_asset",
        lambda *_args: ((assets / "workspace.mk").read_bytes(), archive),
    )
    runner = CliRunner()
    args = ["workspace", "sync", "--project", str(project)]
    if mode != "fresh":
        assert runner.invoke(cli, args).exit_code == 0
        (cached_scripts(project) / "quarto-check.sh").unlink()

        def offline(*_args):
            raise workspace_module.click.ClickException("offline")

        monkeypatch.setattr(workspace_module, "load_asset", offline)
    (project / "scripts").mkdir()
    for name in workspace_module.SCRIPTS:
        (project / "scripts" / name).write_text("echo project-copy\n")
    flags = ["--require-scripts"]
    if mode == "offline-refresh":
        flags.append("--refresh")
    checked = runner.invoke(cli, args + flags)
    assert checked.exit_code == 0, checked.output
    for name in workspace_module.SCRIPTS:
        (project / "scripts" / name).unlink()
    built = subprocess.run(
        [make, "-o", "workspace-assets", "check", "preview-baseline", "preview-ready"],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr
    assert "managed-quarto-check.sh" in built.stdout
    assert built.stdout.count("managed-wait-for-preview.sh") == 2


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("source", ["old-rules", "no-scripts", "one-script"])
def test_require_scripts_rejects_unsupported_source_without_changing_project(
    tmp_path: Path, monkeypatch, cached: bool, source: str
) -> None:
    project = project_with_ref(tmp_path, "v0.105.0")
    rules = workspace_module.MANAGED_SCRIPTS_MARKER + b"\ncheck:\n\t@true\n"
    if source == "old-rules":
        rules = b"check:\n\tsh scripts/quarto-check.sh\n"
    scripts = (
        {workspace_module.ASSET_DIR + "quarto-check.sh": b"echo check\n"}
        if source == "one-script"
        else {}
    )
    archive = _archive(scripts, scripts=source == "old-rules")
    monkeypatch.setattr(workspace_module, "load_asset", lambda *_args: (rules, archive))
    runner = CliRunner()
    args = ["workspace", "sync", "--project", str(project)]
    if cached:
        assert runner.invoke(cli, args).exit_code == 0
    (project / "scripts").mkdir()
    custom = project / "scripts/quarto-check.sh"
    custom.write_text("customized\n")
    before = {
        p.relative_to(project): p.read_bytes()
        for p in project.rglob("*")
        if p.is_file()
    }
    result = runner.invoke(cli, args + ["--require-scripts"])
    assert result.exit_code != 0
    assert "keep the project scripts or select a newer ref" in result.output
    after = {
        p.relative_to(project): p.read_bytes()
        for p in project.rglob("*")
        if p.is_file()
    }
    assert before == after


def test_require_scripts_does_not_certify_local_rules_override(tmp_path: Path) -> None:
    project = project_with_ref(tmp_path, "main")
    (project / "workspace.mk").write_text("check:\n\tsh scripts/custom.sh\n")
    result = CliRunner().invoke(
        cli, ["workspace", "sync", "--project", str(project), "--require-scripts"]
    )
    assert result.exit_code != 0
    assert "Local workspace.mk overrides managed rules" in result.output
    assert not (project / ".asta").exists()


@pytest.mark.parametrize(
    "damage", ["missing", "corrupt", "legacy-manifest", "legacy-layout"]
)
@pytest.mark.parametrize("refresh", [False, True])
def test_sync_repairs_scripts_offline_from_verified_archive(
    tmp_path: Path, monkeypatch, damage: str, refresh: bool
) -> None:
    project = project_with_ref(tmp_path, "main")
    payloads = {name: f"echo {name}".encode() for name in workspace_module.SCRIPTS}
    archive = _archive(
        {workspace_module.ASSET_DIR + name: data for name, data in payloads.items()}
    )
    monkeypatch.setattr(workspace_module, "load_asset", lambda r, f: (b"rule", archive))
    runner = CliRunner()
    args = ["workspace", "sync", "--project", str(project)]
    assert runner.invoke(cli, args).exit_code == 0
    cache = project / ".asta/cache"
    rules = (cache / "workspace.mk").read_bytes()
    script = cached_scripts(project) / "quarto-check.sh"
    if damage == "missing":
        script.unlink()
    elif damage == "corrupt":
        script.write_text("corrupt")
    elif damage == "legacy-manifest":
        manifest = cache / "workspace.json"
        state = json.loads(manifest.read_text())
        del state["scripts"]
        manifest.write_text(json.dumps(state))
        shutil.rmtree(cache / "scripts")
    else:
        manifest = cache / "workspace.json"
        state = json.loads(manifest.read_text())
        generation = cached_scripts(project)
        for name in payloads:
            (generation / name).rename(cache / "scripts" / name)
        generation.rmdir()
        rules = rules.split(b"\n", 1)[1]
        (cache / "workspace.mk").write_bytes(rules)
        state["sha256"] = workspace_module.hashlib.sha256(rules).hexdigest()
        manifest.write_text(json.dumps(state))
    (project / "scripts").mkdir()
    override = project / "scripts/quarto-check.sh"
    override.write_text("custom check")
    calls = []

    def offline(*_args):
        calls.append(True)
        raise workspace_module.click.ClickException("offline")

    monkeypatch.setattr(workspace_module, "load_asset", offline)
    result = runner.invoke(cli, args + (["--refresh"] if refresh else []))
    assert result.exit_code == 0, result.output
    assert len(calls) == int(refresh)
    if damage == "legacy-layout":
        assert (cache / "workspace.mk").read_bytes().endswith(rules)
    else:
        assert (cache / "workspace.mk").read_bytes() == rules
    assert override.read_text() == "custom check"
    for name, data in payloads.items():
        assert (cached_scripts(project) / name).read_bytes() == data
    assert json.loads((cache / "workspace.json").read_text())["scripts"] == (
        workspace_module._scripts_state(
            cached_scripts(project), {name: "" for name in payloads}
        )
    )
    assert runner.invoke(cli, args).exit_code == 0
    assert len(calls) == int(refresh)


@pytest.mark.parametrize("invalid", ["archive", "ref", "source-sha", "repository"])
def test_script_repair_rejects_unverified_or_mismatched_cache(
    tmp_path: Path, monkeypatch, invalid: str
) -> None:
    project = project_with_ref(tmp_path, "main")
    archive = _archive(
        {
            workspace_module.ASSET_DIR + name: b"script"
            for name in workspace_module.SCRIPTS
        }
    )
    monkeypatch.setattr(workspace_module, "load_asset", lambda r, f: (b"rule", archive))
    args = ["workspace", "sync", "--project", str(project)]
    runner = CliRunner()
    assert runner.invoke(cli, args).exit_code == 0
    missing = cached_scripts(project) / "quarto-check.sh"
    missing.unlink()
    if invalid == "archive":
        next((project / ".asta/cache/archives").iterdir()).write_bytes(b"corrupt")
    elif invalid == "source-sha":
        monkeypatch.setenv("ASTA_WORKSPACE_RESOLVED_SHA", "a" * 40)
    else:
        workflow = project / ".github/workflows/docs.yml"
        old, new = (
            ("@main", "@latest") if invalid == "ref" else ("allenai/", "example/")
        )
        workflow.write_text(workflow.read_text().replace(old, new))

    def offline(*_args):
        raise workspace_module.click.ClickException("offline")

    monkeypatch.setattr(workspace_module, "load_asset", offline)
    result = runner.invoke(cli, args)
    assert result.exit_code != 0
    assert "offline" in result.output
    assert not missing.exists()


def cached_scripts(project: Path) -> Path:
    state = json.loads((project / ".asta/cache/workspace.json").read_text())
    return project / ".asta/cache/scripts" / state["archive_sha256"]


@pytest.mark.parametrize(
    "digest", ["../outside", "/outside", "$(shell false)", "A" * 64, None, 123]
)
def test_invalid_archive_digest_cannot_certify_or_repair_cache(
    tmp_path: Path, monkeypatch, digest
) -> None:
    project = project_with_ref(tmp_path, "main")
    rules = workspace_module.MANAGED_SCRIPTS_MARKER + b"\n"
    monkeypatch.setattr(
        workspace_module, "load_asset", lambda *_: (rules, _archive({}))
    )
    args = ["workspace", "sync", "--project", str(project), "--require-scripts"]
    runner = CliRunner()
    assert runner.invoke(cli, args).exit_code == 0
    missing = cached_scripts(project) / "quarto-check.sh"
    missing.unlink()
    manifest = project / ".asta/cache/workspace.json"
    state = json.loads(manifest.read_text())
    state["archive_sha256"] = digest
    manifest.write_text(json.dumps(state))
    before = {path: path.read_bytes() for path in project.rglob("*") if path.is_file()}

    def offline(*_args):
        raise workspace_module.click.ClickException("offline")

    monkeypatch.setattr(workspace_module, "load_asset", offline)
    result = runner.invoke(cli, args)
    assert result.exit_code != 0
    assert "offline" in result.output
    assert not missing.exists()
    assert before == {
        path: path.read_bytes() for path in project.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("present", [[], ["quarto-check.sh"]])
def test_sync_accepts_older_archives_with_missing_scripts(
    tmp_path, monkeypatch, present
) -> None:
    project = project_with_ref(tmp_path, "v0.105.0")
    archive = _archive(
        {workspace_module.ASSET_DIR + name: b"echo old" for name in present},
        scripts=False,
    )
    monkeypatch.setattr(workspace_module, "load_asset", lambda *_: (b"rule", archive))
    runner = CliRunner()
    args = ["workspace", "sync", "--project", str(project)]
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output
    state = json.loads((project / ".asta/cache/workspace.json").read_text())
    assert set(state["scripts"]) == set(present)
    monkeypatch.setattr(
        workspace_module, "load_asset", lambda *_: pytest.fail("offline cache fetched")
    )
    assert runner.invoke(cli, args).exit_code == 0


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
def test_missing_managed_script_reports_sync_guidance(tmp_path: Path) -> None:
    assets = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets"
    )
    shutil.copy(assets / "workspace.mk", tmp_path / "Makefile")
    result = subprocess.run(
        ["make", "-s", "preview-ready"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "update the Asta CLI" in result.stderr
    assert "asta workspace sync --refresh" in result.stderr
    assert "add scripts/wait-for-preview.sh to customize it" in result.stderr


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
@pytest.mark.parametrize("committed", [False, True])
def test_workspace_rules_prefer_committed_script(tmp_path: Path, committed) -> None:
    assets = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets"
    )
    shutil.copy(assets / "workspace.mk", tmp_path / "workspace.mk")
    cached = tmp_path / ".asta/cache/scripts/wait-for-preview.sh"
    cached.parent.mkdir(parents=True)
    cached.write_text('echo "cached $1"\n')
    if committed:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts/wait-for-preview.sh").write_text('echo "project $1"\n')
    result = subprocess.run(
        ["make", "-s", "-f", "workspace.mk", "preview-ready"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ("project wait" if committed else "cached wait")


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
@pytest.mark.parametrize("interrupted_at", ["script", "rules", "manifest", None])
def test_refresh_keeps_rules_and_scripts_on_one_version(
    tmp_path, monkeypatch, interrupted_at
) -> None:
    project = project_with_ref(tmp_path, "main")
    version = 1

    def fetch(*_args):
        rules = (
            f"probe:\n\t@echo rules-{version}\n"
            "\t@sh $(ASTA_WORKSPACE_SCRIPTS)/quarto-check.sh\n"
        ).encode()
        archive = _archive(
            {
                workspace_module.ASSET: rules,
                workspace_module.ASSET_DIR
                + "quarto-check.sh": f"echo script-{version}\n".encode(),
            }
        )
        return rules, archive

    monkeypatch.setattr(workspace_module, "load_asset", fetch)
    runner = CliRunner()
    args = ["workspace", "sync", "--project", str(project)]
    assert runner.invoke(cli, args).exit_code == 0
    old_scripts = cached_scripts(project)
    old_rules = (project / ".asta/cache/workspace.mk").read_bytes()
    write = workspace_module._atomic_write
    version = 2

    def interrupt(path, data):
        if (
            (interrupted_at == "script" and path.name == "wait-for-preview.sh")
            or (interrupted_at == "rules" and path.name == "workspace.mk")
            or (interrupted_at == "manifest" and path.name == "workspace.json")
        ):
            raise OSError("interrupted")
        write(path, data)

    monkeypatch.setattr(workspace_module, "_atomic_write", interrupt)
    result = runner.invoke(cli, args + ["--refresh"])
    assert (result.exit_code == 0) == (interrupted_at is None)
    assert (old_scripts / "quarto-check.sh").read_text() == "echo script-1\n"
    old_reader = project / "old-rules.mk"
    old_reader.write_bytes(old_rules)
    for path, expected in (
        (old_reader, 1),
        (
            project / ".asta/cache/workspace.mk",
            2 if interrupted_at in ("manifest", None) else 1,
        ),
    ):
        result = subprocess.run(
            ["make", "-s", "-f", str(path), "probe"],
            cwd=project,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == f"rules-{expected}\nscript-{expected}\n"


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
def test_ejected_rules_and_scripts_work_without_cli_or_cache(tmp_path) -> None:
    assets = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets"
    )
    shutil.copy(assets / "workspace.mk", tmp_path / "workspace.mk")
    (tmp_path / "Makefile").write_text("include workspace.mk\n")
    (tmp_path / "scripts").mkdir()
    for name in workspace_module.SCRIPTS:
        (tmp_path / "scripts" / name).write_text(f'echo "ejected-{name} $1"\n')
    result = subprocess.run(
        [
            shutil.which("make"),
            "-s",
            "-o",
            "workspace-assets",
            "check",
            "preview-baseline",
            "preview-ready",
        ],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "ejected-quarto-check.sh ",
        "ejected-wait-for-preview.sh baseline",
        "ejected-wait-for-preview.sh wait",
    ]
    assert not (tmp_path / ".asta").exists()


@pytest.mark.parametrize("name", workspace_module.SCRIPTS)
def test_empty_archived_script_is_rejected(name) -> None:
    with pytest.raises(
        workspace_module.click.ClickException, match="Empty or oversized"
    ):
        workspace_module.load_scripts(
            _archive({workspace_module.ASSET_DIR + name: b""})
        )


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
def test_full_makefile_preview_helpers_need_no_cli_or_cache(tmp_path) -> None:
    assets = (
        Path(__file__).resolve().parents[1]
        / "plugins/asta-tools/skills/workspace/assets"
    )
    shutil.copy(assets / "Makefile", tmp_path / "Makefile")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/wait-for-preview.sh").write_text('echo "project $1"\n')
    for target, expected in [
        ("preview-baseline", "baseline"),
        ("preview-ready", "wait"),
    ]:
        result = subprocess.run(
            [shutil.which("make"), "-s", target],
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin"},
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"project {expected}"
    assert not (tmp_path / ".asta").exists()
