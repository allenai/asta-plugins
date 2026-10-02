"""Cross-plugin skill references must resolve and be installable.

asta-assistant, asta-flows and asta-dev call asta-tools skills, so each
marketplace entry must declare the plugins it references in `dependencies`;
otherwise `/plugin install <layer>` installs skills whose calls fail.
"""

import json
import re
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


GUARD = "## Requires asta-tools"


def test_layer_skills_calling_asta_tools_carry_guard():
    # npx plugins/skills ignore `dependencies`, so a hand-picked install can
    # omit asta-tools; the guard makes the skill stop with the install command.
    missing = []
    for md in PLUGINS_ROOT.glob("*/skills/*/SKILL.md"):
        if md.parts[-4] == "asta-tools":
            continue
        text = md.read_text()
        if "Skill(asta-tools:" in text and GUARD not in text:
            missing.append(str(md.relative_to(REPO_ROOT)))
    assert not missing, f"add the '{GUARD}' section to: {missing}"
