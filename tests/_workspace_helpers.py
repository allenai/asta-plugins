"""Shared workspace workflow and release-archive fixtures."""

import io
import shutil
import subprocess
import tarfile
from pathlib import Path

from asta.commands import workspace as workspace_module


def copy_tracked(source: Path, destination: Path) -> None:
    """Copy only git-tracked files: a checkout's ignored caches can be gigabytes."""
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=source, check=True, capture_output=True
    ).stdout.decode()
    for name in filter(None, listed.split("\0")):
        path = source / name
        if not path.exists() and not path.is_symlink():
            continue  # deleted in the working tree
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target, follow_symlinks=False)


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
