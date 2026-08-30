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


def _make_evidence_archive(archive: Path) -> None:
    """Write a tarball whose layout mirrors an asta-plugins source archive."""
    archive_root = archive.parent / "asta-plugins-test"
    source = archive_root / WORKSPACE_ASSETS / "_extensions/evidence"
    if source.exists():
        shutil.rmtree(source)
    shutil.copytree(WORKSPACE_ASSETS / "_extensions/evidence", source)
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)


def test_workspace_makefile_resolves_latest_version_tag(tmp_path: Path) -> None:
    # A local git repo standing in for asta-plugins: git ls-remote reads its
    # tags, and curl reads a co-located archive/ dir via file://. The default
    # (no ASTA_PLUGINS_REF, no ASTA_PLUGINS_ARCHIVE_URL) must pick the highest
    # semver tag and skip non-version tags.
    repo = tmp_path / "asta-plugins"
    (repo / "archive").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "seed",
            "--no-gpg-sign",
        ],
        check=True,
    )
    for tag in ("v0.2.0", "v0.10.0", "v0.9.0", "v2-reproduction-work"):
        subprocess.run(["git", "-C", str(repo), "tag", tag], check=True)

    # Only the latest semver tag's archive exists; if resolution picked any
    # other ref (main, v2-reproduction-work, v0.9.0), the curl would 404.
    _make_evidence_archive(repo / "archive/v0.10.0.tar.gz")

    project = tmp_path / "project"
    project.mkdir()
    env = {
        "ASTA_PLUGINS_REPO": repo.as_uri(),
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

    assert result.returncode == 0, result.stderr
    assert "asta-plugins@v0.10.0" in result.stdout
    assert (project / "_extensions/evidence/snippet.lua").read_bytes() == (
        WORKSPACE_ASSETS / "_extensions/evidence/snippet.lua"
    ).read_bytes()
