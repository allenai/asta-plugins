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


def source_archive(tmp_path, theme=True, invalid_asset=None, damage="missing"):
    root = tmp_path / "source/asta-plugins-test"
    extensions = root / "plugins/asta-tools/skills/workspace/assets/_extensions"
    for name in ("evidence", "asta-theme") if theme else ("evidence",):
        shutil.copytree(ASSETS / "_extensions" / name, extensions / name)
    if invalid_asset:
        path = extensions / "asta-theme" / invalid_asset
        path.unlink()
        if damage == "empty":
            path.touch()
        elif damage == "directory":
            path.mkdir()
        elif damage == "symlink":
            path.symlink_to("../asta.css")
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(root, arcname=root.name)
    return archive


@pytest.mark.parametrize("rules", ["workspace.mk", "Makefile"])
@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("damage", ["missing", "empty", "directory", "symlink"])
@pytest.mark.parametrize(
    "asset",
    [
        "fonts/Manrope.woff2",
        "fonts/RobotoMono.woff2",
        "fonts/Manrope-OFL.txt",
        "fonts/RobotoMono-OFL.txt",
    ],
)
def test_incomplete_theme_is_rejected_before_replacing_any_extension(
    tmp_path, rules, cached, damage, asset
):
    project = tmp_path / "project"
    project.mkdir()
    config = (ASSETS / "_quarto.yml").read_bytes()
    (project / "_quarto.yml").write_bytes(config)
    if cached:
        shutil.copytree(ASSETS / "_extensions", project / "_extensions")
        (project / "_extensions/evidence/previous.txt").write_text("cached evidence")
        (project / "_extensions/asta-theme/previous.txt").write_text("cached theme")

    def snapshot():
        return {
            path.relative_to(project): path.read_bytes()
            for path in (project / "_extensions").rglob("*")
            if path.is_file()
        }

    before = snapshot()
    archive = source_archive(tmp_path, invalid_asset=asset, damage=damage)
    result = install(project, archive, rules)
    assert result.returncode != 0
    assert "incomplete asta-theme" in result.stderr
    assert asset in result.stderr
    assert "installed" not in result.stdout
    assert snapshot() == before
    assert (project / "_quarto.yml").read_bytes() == config
    assert not (project / "_extensions/.evidence-install.lock").exists()


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


@pytest.mark.parametrize("cache", ["complete", "without-fonts", "none"])
def test_offline_render_needs_all_referenced_assets(tmp_path, cache):
    (tmp_path / "_quarto.yml").write_bytes((ASSETS / "_quarto.yml").read_bytes())
    shutil.copytree(ASSETS / "_extensions/evidence", tmp_path / "_extensions/evidence")
    if cache != "none":
        shutil.copytree(
            ASSETS / "_extensions/asta-theme", tmp_path / "_extensions/asta-theme"
        )
    if cache == "without-fonts":
        shutil.rmtree(tmp_path / "_extensions/asta-theme/fonts")
    result = install(tmp_path, tmp_path / "missing.tar.gz")
    assert (result.returncode == 0) is (cache == "complete")


@pytest.mark.parametrize("customization", ["symlink", "committed"])
def test_custom_theme_survives_refresh(tmp_path, customization):
    project = tmp_path / "project"
    target = project / "_extensions/asta-theme"
    target.parent.mkdir(parents=True)
    (project / "_quarto.yml").write_bytes((ASSETS / "_quarto.yml").read_bytes())
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


@pytest.mark.parametrize("rules", ["workspace.mk", "Makefile"])
@pytest.mark.parametrize(
    "config", [None, "format:\n  html:\n    theme: flatly\n    css: styles.css\n"]
)
def test_unused_theme_is_not_installed_or_refreshed(tmp_path, rules, config):
    project = tmp_path / "project"
    project.mkdir()
    if config is not None:
        (project / "_quarto.yml").write_text(config)
    archive = source_archive(tmp_path)
    result = install(project, archive, rules)
    assert result.returncode == 0, result.stderr
    assert (project / "_extensions/evidence/snippet.lua").is_file()
    theme = project / "_extensions/asta-theme"
    assert not theme.exists()

    # A project may have cached the theme before opting out. Preserve it rather
    # than refreshing an unused directory or deleting project-owned content.
    theme.mkdir()
    (theme / "local.txt").write_text("unused theme")
    result = install(project, archive, rules)
    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in theme.iterdir()) == ["local.txt"]
    assert (theme / "local.txt").read_text() == "unused theme"


@pytest.mark.parametrize("rules", ["workspace.mk", "Makefile"])
@pytest.mark.parametrize(
    "cached", [(), ("evidence",), ("asta-theme",), ("evidence", "asta-theme")]
)
@pytest.mark.parametrize("failure", ["before", "after"])
def test_failed_theme_install_restores_the_entire_previous_state(
    tmp_path, monkeypatch, rules, cached, failure
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "_quarto.yml").write_bytes((ASSETS / "_quarto.yml").read_bytes())
    for extension in cached:
        target = project / "_extensions" / extension
        target.mkdir(parents=True)
        (target / "previous.txt").write_text(f"previous {extension}")
    archive = source_archive(tmp_path)

    # Fail the second replacement, including a move that changed the destination
    # before reporting failure. Backup restoration must still use the real mv.
    real_mv = shutil.which("mv")
    assert real_mv is not None
    tools = tmp_path / "tools"
    tools.mkdir()
    wrapper = tools / "mv"
    wrapper.write_text(
        "#!/bin/sh\n"
        'case "$1:$2" in\n'
        "  */new/asta-theme:_extensions/asta-theme)\n"
        '    if [ "$ASTA_TEST_MOVE_FAILURE" = after ]; then\n'
        '      "$ASTA_TEST_REAL_MV" "$@" || exit $?\n'
        "    fi\n"
        '    echo "injected theme move failure" >&2\n'
        "    exit 1 ;;\n"
        "esac\n"
        'exec "$ASTA_TEST_REAL_MV" "$@"\n'
    )
    wrapper.chmod(0o755)
    with monkeypatch.context() as patched:
        patched.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
        patched.setenv("ASTA_TEST_REAL_MV", real_mv)
        patched.setenv("ASTA_TEST_MOVE_FAILURE", failure)
        result = install(project, archive, rules)

    assert result.returncode != 0
    assert "injected theme move failure" in result.stderr
    for extension in ("evidence", "asta-theme"):
        target = project / "_extensions" / extension
        if extension in cached:
            assert sorted(path.name for path in target.iterdir()) == ["previous.txt"]
            assert (target / "previous.txt").read_text() == f"previous {extension}"
        else:
            assert not target.exists()
    assert not (project / "_extensions/.evidence-install.lock").exists()

    # A failed transaction must release the lock and allow a clean retry.
    retried = install(project, archive, rules)
    assert retried.returncode == 0, retried.stderr
    assert (project / "_extensions/evidence/snippet.lua").is_file()
    assert (project / "_extensions/asta-theme/dark.scss").is_file()
