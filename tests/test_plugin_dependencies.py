"""Cross-plugin skill references must resolve and be installable.

asta-assistant, asta-flows and asta-dev call asta-tools skills, so each
marketplace entry must declare the plugins it references in `dependencies`;
otherwise `/plugin install <layer>` installs skills whose calls fail.
"""

import json
import os
import re
import shutil
import subprocess
from functools import cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = json.loads(
    (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text()
)
ENTRIES = {e["name"]: e for e in MARKETPLACE["plugins"]}
REF = re.compile(
    r"(?<![\w/.-])/?(asta-[a-z0-9]+(?:-[a-z0-9]+)*):([a-z0-9*][a-z0-9*-]*)"
)


@cache
def _plugin_path(plugin: str) -> Path:
    source = ENTRIES[plugin]["source"]
    assert isinstance(source, str), f"{plugin}: marketplace source must be local"
    path = (REPO_ROOT / source).resolve()
    assert path.is_relative_to(REPO_ROOT), plugin
    assert path.is_dir(), f"{plugin}: marketplace source does not exist: {path}"
    return path


@cache
def _skill_names(plugin: str) -> set[str]:
    names = set()
    for md in (_plugin_path(plugin) / "skills").glob("*/SKILL.md"):
        m = re.search(r"^name:\s*(.+)", md.read_text(), re.MULTILINE)
        names.add(m.group(1).strip() if m else md.parent.name)
    return names


def _references() -> list[tuple[str, str, str, Path]]:
    refs = []
    for plugin in ENTRIES:
        for md in _plugin_path(plugin).rglob("*.md"):
            for target, skill in REF.findall(md.read_text()):
                refs.append((plugin, target, skill, md))
    return refs


def _dependencies(plugin: str) -> set[str]:
    return {
        dependency if isinstance(dependency, str) else dependency["name"]
        for dependency in ENTRIES[plugin].get("dependencies", [])
    }


def test_marketplace_plugins_include_skills():
    for plugin in ENTRIES:
        path = _plugin_path(plugin)
        assert list((path / "skills").glob("*/SKILL.md")), (
            f"{plugin}: marketplace source has no skills: {path}"
        )


def test_references_resolve():
    bad = []
    for _, target, skill, md in _references():
        rel = md.relative_to(REPO_ROOT)
        if target not in ENTRIES:
            bad.append(f"{rel}: unknown plugin {target}:{skill}")
        elif skill != "*" and skill not in _skill_names(target):
            bad.append(f"{rel}: {target} has no skill {skill}")
    assert not bad, "\n".join(bad)


def test_cross_plugin_references_are_declared_dependencies():
    bad = []
    for plugin, target, skill, md in _references():
        deps = _dependencies(plugin)
        if target != plugin and target in ENTRIES and target not in deps:
            rel = md.relative_to(REPO_ROOT)
            bad.append(f"{rel}: {target}:{skill} but {plugin} lacks that dependency")
    assert not bad, "\n".join(bad)


def test_layers_depend_on_asta_tools():
    for name in ("asta-assistant", "asta-flows", "asta-dev"):
        assert "asta-tools" in _dependencies(name), name


def test_reference_pattern_catches_long_plugin_names():
    assert REF.findall("Skill(asta-paper-flow2:render)") == [
        ("asta-paper-flow2", "render")
    ]
    assert REF.findall("/asta-paper-flow2:render") == [("asta-paper-flow2", "render")]


def test_claude_selective_install_includes_asta_tools(tmp_path):
    if os.environ.get("ASTA_TEST_CLAUDE_PLUGIN_DEPS") != "1":
        pytest.skip("set ASTA_TEST_CLAUDE_PLUGIN_DEPS=1 to run the Claude Code check")
    if not shutil.which("claude"):
        pytest.fail("Claude Code CLI is required for the dependency integration test")

    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "claude-config"),
        "DISABLE_TELEMETRY": "1",
        "DISABLE_AUTOUPDATER": "1",
    }
    for command in (
        ["claude", "plugin", "marketplace", "add", str(REPO_ROOT)],
        ["claude", "plugin", "install", "asta-assistant@asta-plugins", "--yes"],
    ):
        subprocess.run(
            command, env=env, check=True, capture_output=True, text=True, timeout=90
        )

    result = subprocess.run(
        ["claude", "plugin", "list", "--json"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    plugins = {plugin["id"]: plugin for plugin in json.loads(result.stdout)}
    assert {"asta-assistant@asta-plugins", "asta-tools@asta-plugins"} <= set(plugins)
    assert plugins["asta-assistant@asta-plugins"]["enabled"]
    assert plugins["asta-tools@asta-plugins"]["enabled"]

    disable = subprocess.run(
        ["claude", "plugin", "disable", "asta-tools@asta-plugins"],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert disable.returncode != 0, disable.stdout + disable.stderr
    disable_output = (disable.stdout + disable.stderr).lower()
    assert re.search(
        r"(?:requir|depend)\w*[^\n]*asta-assistant|asta-assistant[^\n]*(?:requir|depend)\w*",
        disable_output,
    ), disable_output
    result = subprocess.run(
        ["claude", "plugin", "list", "--json"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    plugins = {plugin["id"]: plugin for plugin in json.loads(result.stdout)}
    assistant_enabled = plugins.get("asta-assistant@asta-plugins", {}).get(
        "enabled", False
    )
    tools_enabled = plugins.get("asta-tools@asta-plugins", {}).get("enabled", False)
    assert assistant_enabled and tools_enabled
