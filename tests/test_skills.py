"""Tests for skill discovery and installation via the skills CLI."""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
ALL_SKILL_MDS = sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))


def _is_internal(skill_md: Path) -> bool:
    return "internal: true" in skill_md.read_text()


def _skill_name(skill_md: Path) -> str:
    match = re.search(r"^name:\s*(.+)", skill_md.read_text(), re.MULTILINE)
    assert match, f"No name field in {skill_md}"
    return match.group(1).strip()


# Derived from SKILL.md frontmatter — single source of truth.
DEFAULT_SKILL_MDS = [s for s in ALL_SKILL_MDS if not _is_internal(s)]
DEFAULT_SKILL_NAMES = {_skill_name(s) for s in DEFAULT_SKILL_MDS}
DEFAULT_SKILL_DIRS = {s.parent.name for s in DEFAULT_SKILL_MDS}
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
        ["npx", "--yes", "skills@latest", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=60,
    )
    return strip_ansi(result.stdout + result.stderr)


class TestSkillSource:
    """Verify canonical skill definitions in skills/."""

    def test_all_skills_have_unique_names(self):
        names = {_skill_name(s) for s in ALL_SKILL_MDS}
        assert len(names) == len(ALL_SKILL_MDS)

    def test_at_least_two_default_skills(self):
        assert len(DEFAULT_SKILL_MDS) >= 2, (
            f"Only {len(DEFAULT_SKILL_MDS)} default skills"
        )

    def test_at_least_one_internal_skill(self):
        internal = [s for s in ALL_SKILL_MDS if _is_internal(s)]
        assert len(internal) >= 1, "No internal skills found"


class TestGeneratedPlugins:
    """Verify generated plugin packages in plugins/."""

    def test_asta_plugin_has_only_default_skills(self):
        plugin_skills = REPO_ROOT / "plugins" / "asta" / "skills"
        assert plugin_skills.is_dir(), "Run 'make build-plugins' first"
        dirs = {d.name for d in plugin_skills.iterdir() if d.is_dir()}
        assert dirs == DEFAULT_SKILL_DIRS

    def test_asta_preview_plugin_has_all_skills(self):
        plugin_skills = REPO_ROOT / "plugins" / "asta-preview" / "skills"
        assert plugin_skills.is_dir(), "Run 'make build-plugins' first"
        dirs = {d.name for d in plugin_skills.iterdir() if d.is_dir()}
        assert dirs == ALL_SKILL_DIRS

    def test_no_plugin_json(self):
        """Generated plugins should not contain plugin.json — marketplace.json is the source."""
        for name in ("asta", "asta-preview"):
            pj = REPO_ROOT / "plugins" / name / ".claude-plugin" / "plugin.json"
            assert not pj.exists(), (
                f"Unexpected {pj} — remove .claude-plugin from generated plugins"
            )

    def test_plugins_match_source(self):
        """Generated plugin skills must be identical to canonical source."""
        for name in ("asta", "asta-preview"):
            plugin_skills = REPO_ROOT / "plugins" / name / "skills"
            for skill_dir in plugin_skills.iterdir():
                if not skill_dir.is_dir():
                    continue
                source = REPO_ROOT / "skills" / skill_dir.name / "SKILL.md"
                generated = skill_dir / "SKILL.md"
                assert source.read_text() == generated.read_text(), (
                    f"plugins/{name}/skills/{skill_dir.name}/SKILL.md differs from source"
                )

    def test_plugins_have_hooks(self):
        """Generated plugins must include hooks from source."""
        source_hooks = REPO_ROOT / "hooks"
        if not source_hooks.is_dir():
            pytest.skip("No hooks/ directory in source")
        source_files = {f.name for f in source_hooks.iterdir() if f.is_file()}
        for name in ("asta", "asta-preview"):
            plugin_hooks = REPO_ROOT / "plugins" / name / "hooks"
            assert plugin_hooks.is_dir(), f"plugins/{name}/hooks/ missing"
            generated_files = {f.name for f in plugin_hooks.iterdir() if f.is_file()}
            assert generated_files == source_files, (
                f"plugins/{name}/hooks/ doesn't match source hooks/"
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
        return {d.name for d in matches[0].iterdir() if d.is_dir()}

    def test_asta_plugin_installs_only_default(self, tmp_home):
        self._install_plugin(tmp_home, "asta")
        assert self._plugin_skill_dirs(tmp_home, "asta") == DEFAULT_SKILL_DIRS

    def test_asta_preview_plugin_installs_all(self, tmp_home):
        self._install_plugin(tmp_home, "asta-preview")
        assert self._plugin_skill_dirs(tmp_home, "asta-preview") == ALL_SKILL_DIRS


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx not available")
class TestNpxSkillDiscovery:
    """Verify npx skills CLI discovery."""

    @pytest.fixture(scope="class")
    def default_output(self):
        return run_skills_cli(["add", str(REPO_ROOT), "--list"])

    @pytest.fixture(scope="class")
    def all_output(self):
        return run_skills_cli(["add", str(REPO_ROOT), "--list", "--all"])

    def test_default_discovers_only_default_skills(self, default_output):
        assert f"Found {len(DEFAULT_SKILL_MDS)} skills" in default_output
        for name in DEFAULT_SKILL_NAMES:
            assert name in default_output

    def test_all_discovers_every_skill(self, all_output):
        assert f"Found {len(ALL_SKILL_MDS)} skills" in all_output


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx not available")
class TestNpxSkillInstallation:
    """Verify npx skills add installs the right skills."""

    def _installed_skill_dirs(self, project_dir: Path) -> set[str]:
        agents_skills = project_dir / ".agents" / "skills"
        if not agents_skills.exists():
            return set()
        return {d.name for d in agents_skills.iterdir() if d.is_dir()}

    def test_default_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_skills_cli(["add", str(REPO_ROOT), "--yes"], cwd=tmpdir)
            installed = self._installed_skill_dirs(Path(tmpdir))
            assert len(installed) == len(DEFAULT_SKILL_MDS)

    def test_all_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_skills_cli(["add", str(REPO_ROOT), "--yes", "--all"], cwd=tmpdir)
            installed = self._installed_skill_dirs(Path(tmpdir))
            assert len(installed) == len(ALL_SKILL_MDS)
