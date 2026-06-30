"""Tests for skill discovery and installation via the skills CLI."""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PLUGINS_ROOT = REPO_ROOT / "plugins"
PLUGIN_NAMES = ("asta-tools", "asta-dev")


def _skill_mds(plugin: str) -> list[Path]:
    return sorted((PLUGINS_ROOT / plugin / "skills").glob("*/SKILL.md"))


def _skill_dirs(plugin: str) -> set[str]:
    return {s.parent.name for s in _skill_mds(plugin)}


def _skill_name(skill_md: Path) -> str:
    match = re.search(r"^name:\s*(.+)", skill_md.read_text(), re.MULTILINE)
    assert match, f"No name field in {skill_md}"
    return match.group(1).strip()


SKILL_DIRS_BY_PLUGIN: dict[str, set[str]] = {p: _skill_dirs(p) for p in PLUGIN_NAMES}
ALL_SKILL_MDS = [md for p in PLUGIN_NAMES for md in _skill_mds(p)]
ALL_SKILL_DIRS = set().union(*SKILL_DIRS_BY_PLUGIN.values())


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def run_skills_cli(
    args: list[str],
    env_override: dict[str, str] | None = None,
    cwd: str | Path | None = None,
) -> str:
    """Run a `npx skills` command and return cleaned output."""
    env = {**os.environ, **(env_override or {})}
    result = subprocess.run(
        # @latest is what `npx skills add` gives users — green means users can
        # install. Override SKILLS_CLI to pin if an upstream release regresses.
        ["npx", "--yes", os.environ.get("SKILLS_CLI", "skills@latest"), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=60,
    )
    return strip_ansi(result.stdout + result.stderr)


class TestSkillSource:
    """Verify skill definitions across all plugins."""

    def test_all_skills_have_unique_names(self):
        names = [_skill_name(s) for s in ALL_SKILL_MDS]
        assert len(set(names)) == len(names), "duplicate skill names across plugins"

    def test_at_least_two_skills_per_plugin(self):
        for plugin, dirs in SKILL_DIRS_BY_PLUGIN.items():
            assert len(dirs) >= 2, f"{plugin}: only {len(dirs)} skills"


class TestPluginLayout:
    """Verify each plugin's filesystem layout."""

    def test_each_plugin_has_expected_skills(self):
        for plugin, expected in SKILL_DIRS_BY_PLUGIN.items():
            plugin_skills = PLUGINS_ROOT / plugin / "skills"
            assert plugin_skills.is_dir(), f"{plugin}: skills dir missing"
            dirs = {
                d.name
                for d in plugin_skills.iterdir()
                if d.is_dir() and (d / "SKILL.md").exists()
            }
            assert dirs == expected

    def test_no_per_plugin_manifests(self):
        """No committed per-plugin manifest in any vendor dir.

        marketplace.json is the single metadata source; `npx plugins add`
        synthesises the per-agent manifests at install. A committed
        `.plugin/`/`.claude-plugin/`/`.codex-plugin/` plugin.json would be a
        second hand-maintained copy that can drift from it.
        """
        for plugin in PLUGIN_NAMES:
            for vendor in (
                ".plugin",
                ".claude-plugin",
                ".codex-plugin",
                ".cursor-plugin",
            ):
                pj = PLUGINS_ROOT / plugin / vendor / "plugin.json"
                assert not pj.exists(), (
                    f"Unexpected {pj} — marketplace.json is the only metadata "
                    "source (avoids drift)"
                )


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude not available")
class TestClaudePluginInstall:
    """Verify Claude Code plugin install from local marketplace."""

    @pytest.fixture(scope="class")
    def tmp_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def _run_claude(self, tmp_home: str, *args: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "HOME": tmp_home}
        return subprocess.run(
            ["claude", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    def _install_plugin(self, tmp_home: str, plugin_name: str):
        self._run_claude(
            tmp_home, "plugin", "marketplace", "add", str(REPO_ROOT), "--scope", "user"
        )
        result = self._run_claude(tmp_home, "plugin", "install", plugin_name)
        assert result.returncode == 0, (
            f"Failed to install {plugin_name}: {result.stderr}"
        )

    def _plugin_skill_dirs(self, tmp_home: str, plugin_name: str) -> set[str]:
        """Return skill directory names from the installed plugin cache."""
        cache = (
            Path(tmp_home)
            / ".claude"
            / "plugins"
            / "cache"
            / "asta-plugins"
            / plugin_name
        )
        # Cache structure: <plugin_name>/<version>/skills/
        matches = list(cache.glob("*/skills"))
        if not matches or not matches[0].is_dir():
            return set()
        return {
            d.name
            for d in matches[0].iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        }

    @pytest.mark.parametrize("plugin", PLUGIN_NAMES)
    def test_plugin_installs_its_skills(self, tmp_home, plugin):
        self._install_plugin(tmp_home, plugin)
        assert self._plugin_skill_dirs(tmp_home, plugin) == SKILL_DIRS_BY_PLUGIN[plugin]


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx not available")
class TestNpxSkillInstallation:
    """End-to-end: `npx skills add` installs every skill from every plugin."""

    def _installed_skill_dirs(self, project_dir: Path) -> set[str]:
        agents_skills = project_dir / ".agents" / "skills"
        if not agents_skills.exists():
            return set()
        return {
            d.name
            for d in agents_skills.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        }

    def test_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_skills_cli(["add", str(REPO_ROOT), "--yes"], cwd=tmpdir)
            installed = self._installed_skill_dirs(Path(tmpdir))
            assert installed == ALL_SKILL_DIRS
