"""Tests for skill discovery and installation via the skills CLI."""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
# Canonical skills live in the asta-preview plugin (the complete superset).
# plugins/asta is generated from it (the core, non-internal subset).
CANONICAL = REPO_ROOT / "plugins" / "asta-preview"
ALL_SKILL_MDS = sorted((CANONICAL / "skills").glob("*/SKILL.md"))


def _is_internal(skill_md: Path) -> bool:
    return "internal: true" in skill_md.read_text()


def _skill_name(skill_md: Path) -> str:
    match = re.search(r"^name:\s*(.+)", skill_md.read_text(), re.MULTILINE)
    assert match, f"No name field in {skill_md}"
    return match.group(1).strip()


# Derived from SKILL.md frontmatter — single source of truth.
DEFAULT_SKILL_MDS = [s for s in ALL_SKILL_MDS if not _is_internal(s)]
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
    """Verify canonical skill definitions in plugins/asta-preview/skills/."""

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


class TestPluginLayout:
    """Verify the asta-preview (canonical) and asta (generated subset) plugins."""

    def test_asta_preview_has_all_skills(self):
        """asta-preview is the canonical superset — it holds every skill."""
        plugin_skills = CANONICAL / "skills"
        assert plugin_skills.is_dir()
        dirs = {d.name for d in plugin_skills.iterdir() if d.is_dir()}
        assert dirs == ALL_SKILL_DIRS

    def test_asta_has_only_core_skills(self):
        """asta is the generated core subset — only non-internal skills."""
        plugin_skills = REPO_ROOT / "plugins" / "asta" / "skills"
        assert plugin_skills.is_dir(), "Run 'make build-plugins' first"
        dirs = {d.name for d in plugin_skills.iterdir() if d.is_dir()}
        assert dirs == DEFAULT_SKILL_DIRS

    def test_no_per_plugin_manifests(self):
        """No committed per-plugin manifest in any vendor dir.

        marketplace.json is the single metadata source; `npx plugins add`
        synthesises the per-agent manifests at install. A committed
        `.plugin/`/`.claude-plugin/`/`.codex-plugin/` plugin.json would be a
        second hand-maintained copy that can drift from it.
        """
        for name in ("asta", "asta-preview"):
            for vendor in (
                ".plugin",
                ".claude-plugin",
                ".codex-plugin",
                ".cursor-plugin",
            ):
                pj = REPO_ROOT / "plugins" / name / vendor / "plugin.json"
                assert not pj.exists(), (
                    f"Unexpected {pj} — marketplace.json is the only metadata "
                    "source (avoids drift)"
                )

    def test_generated_asta_matches_canonical(self):
        """Each generated asta skill must be byte-identical to its canonical asta-preview source."""
        asta_skills = REPO_ROOT / "plugins" / "asta" / "skills"
        for skill_dir in asta_skills.iterdir():
            if not skill_dir.is_dir():
                continue
            source = CANONICAL / "skills" / skill_dir.name / "SKILL.md"
            generated = skill_dir / "SKILL.md"
            assert source.read_text() == generated.read_text(), (
                f"plugins/asta/skills/{skill_dir.name}/SKILL.md differs from canonical"
            )

    def test_generated_asta_hooks_match_canonical(self):
        """Generated asta hooks must be byte-identical to the canonical hooks."""
        source_hooks = CANONICAL / "hooks"
        assert source_hooks.is_dir(), "canonical hooks missing"
        asta_hooks = REPO_ROOT / "plugins" / "asta" / "hooks"
        assert asta_hooks.is_dir(), "plugins/asta/hooks/ missing"
        source_files = {f.name for f in source_hooks.iterdir() if f.is_file()}
        generated_files = {f.name for f in asta_hooks.iterdir() if f.is_file()}
        assert generated_files == source_files, (
            "plugins/asta/hooks/ doesn't match canonical hooks"
        )
        for f in source_hooks.iterdir():
            if f.is_file():
                assert (asta_hooks / f.name).read_bytes() == f.read_bytes(), (
                    f"plugins/asta/hooks/{f.name} differs from canonical"
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
class TestNpxSkillInstallation:
    """End-to-end: `npx skills add` installs exactly the expected split.

    TestPluginLayout asserts the split from the filesystem (no CLI); this
    confirms the real installer reproduces that exact set end-to-end. Both
    plugins carry the core skills (asta is a subset of asta-preview), so the
    exact-set assertion also proves the CLI dedupes across them rather than
    double-installing or needing a plugin preference.
    """

    def _installed_skill_dirs(self, project_dir: Path) -> set[str]:
        agents_skills = project_dir / ".agents" / "skills"
        if not agents_skills.exists():
            return set()
        return {d.name for d in agents_skills.iterdir() if d.is_dir()}

    def test_default_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_skills_cli(["add", str(REPO_ROOT), "--yes"], cwd=tmpdir)
            installed = self._installed_skill_dirs(Path(tmpdir))
            # Exact set, not just count — the real CLI must install precisely
            # the core skills.
            assert installed == DEFAULT_SKILL_DIRS

    def test_all_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_skills_cli(["add", str(REPO_ROOT), "--yes", "--all"], cwd=tmpdir)
            installed = self._installed_skill_dirs(Path(tmpdir))
            assert installed == ALL_SKILL_DIRS
