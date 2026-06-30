"""Tests for skill discovery and installation via the skills CLI."""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PLUGIN = REPO_ROOT / "plugins" / "asta-tools"
ALL_SKILL_MDS = sorted((PLUGIN / "skills").glob("*/SKILL.md"))


def _skill_name(skill_md: Path) -> str:
    match = re.search(r"^name:\s*(.+)", skill_md.read_text(), re.MULTILINE)
    assert match, f"No name field in {skill_md}"
    return match.group(1).strip()


ALL_SKILL_DIRS = {s.parent.name for s in ALL_SKILL_MDS}


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
    """Verify skill definitions in plugins/asta-tools/skills/."""

    def test_all_skills_have_unique_names(self):
        names = {_skill_name(s) for s in ALL_SKILL_MDS}
        assert len(names) == len(ALL_SKILL_MDS)

    def test_at_least_two_skills(self):
        assert len(ALL_SKILL_MDS) >= 2, f"Only {len(ALL_SKILL_MDS)} skills"


class TestPluginLayout:
    """Verify the asta-tools plugin layout."""

    def test_asta_tools_has_all_skills(self):
        plugin_skills = PLUGIN / "skills"
        assert plugin_skills.is_dir()
        dirs = {
            d.name
            for d in plugin_skills.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        }
        assert dirs == ALL_SKILL_DIRS

    def test_no_per_plugin_manifests(self):
        """No committed per-plugin manifest in any vendor dir.

        marketplace.json is the single metadata source; `npx plugins add`
        synthesises the per-agent manifests at install. A committed
        `.plugin/`/`.claude-plugin/`/`.codex-plugin/` plugin.json would be a
        second hand-maintained copy that can drift from it.
        """
        for vendor in (
            ".plugin",
            ".claude-plugin",
            ".codex-plugin",
            ".cursor-plugin",
        ):
            pj = PLUGIN / vendor / "plugin.json"
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

    def test_asta_tools_plugin_installs_all(self, tmp_home):
        self._install_plugin(tmp_home, "asta-tools")
        assert self._plugin_skill_dirs(tmp_home, "asta-tools") == ALL_SKILL_DIRS


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx not available")
class TestNpxSkillInstallation:
    """End-to-end: `npx skills add` installs every skill from asta-tools."""

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
