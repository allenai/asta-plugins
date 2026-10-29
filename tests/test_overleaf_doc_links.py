"""Every Overleaf recovery anchor the CLI prints and every link between the
Overleaf docs must resolve to a heading."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "plugins/asta-tools/skills/workspace/workflows"
RECOVERY = WORKFLOWS / "overleaf-recovery.md"
DOCS = [
    ROOT / "docs/overleaf-sync.md",
    ROOT / "plugins/asta-tools/skills/workspace/assets/DEVELOPER.md",
    *sorted(WORKFLOWS.glob("overleaf-*.md")),
]
BLOB = re.compile(r"https://github\.com/allenai/asta-plugins/blob/[^/]+/")
LINK = re.compile(r"\]\(([^)\s]+)\)")


def anchors(path: Path) -> set[str]:
    """GitHub heading slugs, without duplicate-suffix handling."""
    slugs = set()
    in_fence = False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and (m := re.match(r"#+\s+(.*)", line)):
            text = re.sub(r"[^\w\- ]", "", m.group(1).strip().lower())
            slugs.add(text.replace(" ", "-"))
    return slugs


def cli_recovery_anchors() -> set[str]:
    src = "\n".join(p.read_text() for p in (ROOT / "src").rglob("*.py"))
    found = set(re.findall(r'recovery="([a-z0-9-]+)"', src))
    found |= set(re.findall(r"RECOVERY\}#([a-z0-9-]+)", src))
    return found


def test_cli_prints_recovery_anchors():
    assert cli_recovery_anchors()


@pytest.mark.parametrize("anchor", sorted(cli_recovery_anchors()))
def test_cli_recovery_anchor_resolves(anchor):
    assert anchor in anchors(RECOVERY)


def doc_links():
    for doc in DOCS:
        for target in LINK.findall(doc.read_text()):
            if BLOB.match(target):
                path, _, frag = BLOB.sub("", target).partition("#")
                resolved = ROOT / path
            elif "://" in target or target.startswith("mailto:"):
                continue
            else:
                path, _, frag = target.partition("#")
                resolved = (doc.parent / path).resolve() if path else doc
            yield pytest.param(doc, resolved, frag, id=f"{doc.name}->{target}")


@pytest.mark.parametrize(("doc", "target", "fragment"), list(doc_links()))
def test_overleaf_doc_link_resolves(doc, target, fragment):
    assert target.exists(), f"{doc}: missing {target}"
    if fragment and target.suffix == ".md":
        assert fragment in anchors(target), f"{doc}: no heading #{fragment}"
