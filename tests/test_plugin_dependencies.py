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

REPO_ROOT = Path(__file__).parent.parent
PLUGINS_ROOT = REPO_ROOT / "plugins"
MARKETPLACE = json.loads(
    (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text()
)
ENTRIES = {e["name"]: e for e in MARKETPLACE["plugins"]}
REF = re.compile(r"(?<![\w/.-])(asta-[a-z0-9]+(?:-[a-z0-9]+)*):([a-z0-9*][a-z0-9*-]*)")


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


def test_layers_check_asta_tools_at_session_start_and_prompt():
    scripts = []
    for name in ("asta-assistant", "asta-flows", "asta-dev"):
        hook_dir = PLUGINS_ROOT / name / "hooks"
        script = hook_dir / "require-asta-tools.sh"
        config = json.loads((hook_dir / "hooks.json").read_text())["hooks"]
        assert script.is_file(), name
        scripts.append(script.read_bytes())
        for event, suffix in (("SessionStart", ""), ("UserPromptSubmit", " block")):
            commands = [
                hook["command"] for group in config[event] for hook in group["hooks"]
            ]
            assert (
                f'bash "${{CLAUDE_PLUGIN_ROOT}}/hooks/require-asta-tools.sh"{suffix}'
                in commands
            )
    assert len(set(scripts)) == 1, "layer dependency checks must stay identical"


def test_missing_asta_tools_blocks_prompt(tmp_path):
    root = tmp_path / "plugins/cache/marketplace/asta-assistant/version"
    root.mkdir(parents=True)
    script = PLUGINS_ROOT / "asta-assistant/hooks/require-asta-tools.sh"
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(root)}
    startup = subprocess.run(
        ["bash", str(script)], env=env, capture_output=True, text=True
    )
    assert startup.returncode == 0
    assert "asta-tools is required" in startup.stdout
    result = subprocess.run(
        ["bash", str(script), "block"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "asta-tools is required" in result.stderr
    assert result.stdout == ""

    skills = tmp_path / "plugins/cache/marketplace/asta-tools/version/skills"
    skills.mkdir(parents=True)
    result = subprocess.run(
        ["bash", str(script), "block"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""


def test_unknown_layout_does_not_block_prompt(tmp_path):
    script = PLUGINS_ROOT / "asta-assistant/hooks/require-asta-tools.sh"
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(tmp_path / "custom-layout/layer")}
    result = subprocess.run(
        ["bash", str(script), "block"],
        env=env,
        input='{"prompt":"write code"}',
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""

    env.pop("CLAUDE_PLUGIN_ROOT")
    env.pop("PLUGIN_ROOT", None)
    result = subprocess.run(
        ["bash", str(script), "block"],
        env=env,
        input='{"prompt":"write code"}',
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""


def test_guard_handles_windows_separators_and_spaced_hook_path(tmp_path):
    root = tmp_path / "space dir/plugins/cache/marketplace/asta-assistant/version"
    hook_dir = root / "hooks"
    hook_dir.mkdir(parents=True)
    shutil.copy2(PLUGINS_ROOT / "asta-assistant/hooks/require-asta-tools.sh", hook_dir)
    command = json.loads(
        (PLUGINS_ROOT / "asta-assistant/hooks/hooks.json").read_text()
    )["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(root).replace("/", "\\")}
    result = subprocess.run(
        ["bash", str(hook_dir / "require-asta-tools.sh"), "block"],
        env=env,
        input='{"prompt":"write code"}',
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2

    env["CLAUDE_PLUGIN_ROOT"] = str(root)
    result = subprocess.run(
        ["bash", "-c", command],
        env=env,
        input='{"prompt":"write code"}',
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "asta-tools is required" in result.stderr


def test_plugin_install_command_remains_available(tmp_path):
    root = tmp_path / "plugins/cache/marketplace/asta-assistant/version"
    root.mkdir(parents=True)
    script = PLUGINS_ROOT / "asta-assistant/hooks/require-asta-tools.sh"
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(root)}
    result = subprocess.run(
        ["bash", str(script), "block"],
        env=env,
        input='{"prompt":"/plugin install asta-tools"}',
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""
