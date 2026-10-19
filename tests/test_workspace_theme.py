"""Exercise extension installation with source releases and offline caches."""

import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

ASSETS = (
    Path(__file__).resolve().parents[1] / "plugins/asta-tools/skills/workspace/assets"
)
pytestmark = pytest.mark.skipif(
    shutil.which("make") is None, reason="make not installed"
)


def install(project, archive, rules="workspace.mk"):
    return subprocess.run(
        ["make", "-f", str(ASSETS / rules), "workspace-assets"],
        cwd=project,
        env={**os.environ, "ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri()},
        capture_output=True,
        text=True,
    )


def source_archive(tmp_path, theme=True):
    root = tmp_path / "source/asta-plugins-test"
    extensions = root / "plugins/asta-tools/skills/workspace/assets/_extensions"
    for name in ("evidence", "asta-theme") if theme else ("evidence",):
        shutil.copytree(ASSETS / "_extensions" / name, extensions / name)
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(root, arcname=root.name)
    return archive


@pytest.mark.parametrize("rules", ["workspace.mk", "Makefile"])
def test_installs_and_refreshes_both_extensions_from_the_same_source(tmp_path, rules):
    project = tmp_path / "project"
    project.mkdir()
    (project / "_quarto.yml").write_bytes((ASSETS / "_quarto.yml").read_bytes())
    archive = source_archive(tmp_path)
    for _ in range(2):
        result = install(project, archive, rules)
        assert result.returncode == 0, result.stderr
        for extension, file in [
            ("evidence", "snippet.lua"),
            ("asta-theme", "dark.scss"),
        ]:
            path = project / "_extensions" / extension / file
            assert (
                path.read_bytes()
                == (ASSETS / "_extensions" / extension / file).read_bytes()
            )
            path.write_text("stale content")


@pytest.mark.parametrize("uses_theme", [True, False])
def test_old_source_only_allowed_for_configurations_without_the_theme(
    tmp_path, uses_theme
):
    project = tmp_path / "project"
    project.mkdir()
    if uses_theme:
        (project / "_quarto.yml").write_bytes((ASSETS / "_quarto.yml").read_bytes())
    archive = source_archive(tmp_path, theme=False)
    result = install(project, archive)
    assert (result.returncode != 0) is uses_theme
    if uses_theme:
        assert "asta-theme extension not found" in result.stderr
        assert not (
            project / "_extensions/evidence"
        ).exists()  # preflight before replacement
    else:
        assert (project / "_extensions/evidence/snippet.lua").is_file()


@pytest.mark.parametrize("complete", [True, False])
def test_offline_render_needs_all_referenced_assets(tmp_path, complete):
    (tmp_path / "_quarto.yml").write_bytes((ASSETS / "_quarto.yml").read_bytes())
    shutil.copytree(ASSETS / "_extensions/evidence", tmp_path / "_extensions/evidence")
    if complete:
        shutil.copytree(
            ASSETS / "_extensions/asta-theme", tmp_path / "_extensions/asta-theme"
        )
    result = install(tmp_path, tmp_path / "missing.tar.gz")
    assert (result.returncode == 0) is complete


@pytest.mark.parametrize("customization", ["symlink", "committed"])
def test_custom_theme_survives_refresh(tmp_path, customization):
    project = tmp_path / "project"
    target = project / "_extensions/asta-theme"
    target.parent.mkdir(parents=True)
    if customization == "symlink":
        local = tmp_path / "my-theme"
        local.mkdir()
        target.symlink_to(local)
    else:
        target.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True)
    (target / "dark.scss").write_text("my theme")
    if customization == "committed":
        subprocess.run(
            ["git", "-C", str(project), "add", "_extensions/asta-theme/dark.scss"],
            check=True,
        )
    result = install(project, source_archive(tmp_path))
    assert result.returncode == 0, result.stderr
    assert (target / "dark.scss").read_text() == "my theme"
