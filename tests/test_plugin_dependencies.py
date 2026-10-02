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
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PLUGINS_ROOT = REPO_ROOT / "plugins"
MARKETPLACE = json.loads(
    (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text()
)
ENTRIES = {e["name"]: e for e in MARKETPLACE["plugins"]}
REF = re.compile(
    r"(?<![\w/.-])/?(asta-[a-z0-9]+(?:-[a-z0-9]+)*):([a-z0-9*][a-z0-9*-]*)"
)


def _skill_names(plugin: str) -> set[str]:
    names = set()
    for md in (PLUGINS_ROOT / plugin / "skills").glob("*/SKILL.md"):
        m = re.search(r"^name:\s*(.+)", md.read_text(), re.MULTILINE)
        names.add(m.group(1).strip() if m else md.parent.name)
    return names


def _references() -> list[tuple[str, str, str, Path]]:
    refs = []
    for plugin in ENTRIES:
        for md in (PLUGINS_ROOT / plugin).rglob("*.md"):
            for target, skill in REF.findall(md.read_text()):
                refs.append((plugin, target, skill, md))
    return refs


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
        deps = {
            d if isinstance(d, str) else d["name"]
            for d in ENTRIES[plugin].get("dependencies", [])
        }
        if target != plugin and target in ENTRIES and target not in deps:
            rel = md.relative_to(REPO_ROOT)
            bad.append(f"{rel}: {target}:{skill} but {plugin} lacks that dependency")
    assert not bad, "\n".join(bad)


def test_layers_depend_on_asta_tools():
    for name in ("asta-assistant", "asta-flows", "asta-dev"):
        assert "asta-tools" in ENTRIES[name].get("dependencies", []), name


def test_reference_pattern_catches_long_plugin_names():
    assert REF.findall("Skill(asta-paper-flow2:render)") == [
        ("asta-paper-flow2", "render")
    ]
    assert REF.findall("/asta-paper-flow2:render") == [("asta-paper-flow2", "render")]


def test_claude_selective_install_includes_asta_tools(tmp_path):
    if not shutil.which("claude"):
        if os.environ.get("CI") == "true":
            pytest.fail(
                "Claude Code CLI is required for the dependency integration test"
            )
        pytest.skip("Claude Code CLI is not installed")

    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "claude-config"),
        "DISABLE_TELEMETRY": "1",
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
    assert "required by asta-assistant" in (disable.stdout + disable.stderr).lower(), (
        disable.stdout + disable.stderr
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
    assistant_enabled = plugins.get("asta-assistant@asta-plugins", {}).get(
        "enabled", False
    )
    tools_enabled = plugins.get("asta-tools@asta-plugins", {}).get("enabled", False)
    assert assistant_enabled and tools_enabled
