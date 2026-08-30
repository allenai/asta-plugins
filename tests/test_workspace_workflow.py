import os
import shutil
import subprocess
import tarfile
from pathlib import Path

WORKFLOW = Path(".github/workflows/workspace-quarto-site.yml")
WORKSPACE_ASSETS = Path("plugins/asta-tools/skills/workspace/assets")


def test_workspace_assets_use_called_workflow_identity() -> None:
    workflow = WORKFLOW.read_text()

    assert workflow.count("${{ job.workflow_repository }}") == 2
    assert workflow.count("${{ job.workflow_sha }}") == 2
    assert "github.job_workflow" not in workflow


def test_workspace_makefile_refreshes_evidence_extension(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive" / "asta-plugins-test"
    source = archive_root / WORKSPACE_ASSETS / "_extensions/evidence"
    shutil.copytree(WORKSPACE_ASSETS / "_extensions/evidence", source)

    archive = tmp_path / "asta-plugins.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)

    project = tmp_path / "project"
    target = project / "_extensions/evidence"
    target.mkdir(parents=True)
    (target / "stale-file").write_text("remove me")

    env = {
        "ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri(),
        "PATH": os.environ["PATH"],
    }
    subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env=env,
        check=True,
    )

    assert not (target / "stale-file").exists()
    assert (target / "snippet.lua").read_bytes() == (
        WORKSPACE_ASSETS / "_extensions/evidence/snippet.lua"
    ).read_bytes()


def test_workspace_makefile_does_not_race_an_active_install(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive" / "asta-plugins-test"
    source = archive_root / WORKSPACE_ASSETS / "_extensions/evidence"
    shutil.copytree(WORKSPACE_ASSETS / "_extensions/evidence", source)

    archive = tmp_path / "asta-plugins.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)

    project = tmp_path / "project"
    target = project / "_extensions/evidence"
    target.mkdir(parents=True)
    sentinel = target / "current-version"
    sentinel.write_text("keep me")
    (project / "_extensions/.evidence-install.lock").mkdir()

    env = {
        "ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri(),
        "PATH": os.environ["PATH"],
    }
    result = subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "another workspace-assets install is in progress" in result.stderr
    assert sentinel.read_text() == "keep me"
