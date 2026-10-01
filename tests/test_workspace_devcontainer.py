"""Static checks that keep the workspace dev container a working Codespaces surface."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "plugins/asta-tools/skills/workspace/assets/devcontainer.json"
DOCKERFILE = ROOT / "Dockerfile"
WORKFLOW = ROOT / ".github/workflows/workspace-quarto-site.yml"
SKILLS_PACKAGE = ROOT / "image/skills-cli/package.json"
SKILLS_LOCK = ROOT / "image/skills-cli/package-lock.json"


def _devcontainer() -> dict:
    return json.loads(ASSET.read_text())


def test_asta_token_is_a_codespaces_secret():
    config = _devcontainer()
    assert "ASTA_TOKEN" in config.get("secrets", {})
    # ${localEnv:...} is empty in Codespaces and would blank the secret.
    assert "localEnv:ASTA_TOKEN" not in json.dumps(config)


def test_preview_port_notifies_and_prints_link():
    config = _devcontainer()
    assert 4848 in config["forwardPorts"]
    # Browser Codespaces needs its forwarded URL; private ports may fail in a frame.
    assert config["portsAttributes"]["4848"]["onAutoForward"] == "notify"
    preview = config["postAttachCommand"]["preview"]
    assert "quarto preview --no-browser --port 4848" in preview
    assert (
        "${CODESPACE_NAME}-4848.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN" in preview
    )
    assert preview.index('echo "Quarto preview: $url"') < preview.index("make preview")


def test_quarto_extension_listed_latex_workshop_rides_the_tex_image():
    extensions = _devcontainer()["customizations"]["vscode"]["extensions"]
    assert "quarto.quarto" in extensions
    assert "james-yu.latex-workshop" not in extensions
    stages = DOCKERFILE.read_text().split("\nFROM ")
    tex_stage = next(s for s in stages if s.startswith("asta AS tex"))
    label = re.search(r"^LABEL devcontainer\.metadata='(.+)'$", tex_stage, re.M)
    assert label, "tex stage must carry devcontainer.metadata"
    metadata = json.loads(label.group(1))
    assert "james-yu.latex-workshop" in json.dumps(metadata)
    assert "latex-workshop" not in "".join(
        s for s in stages if not s.startswith("asta AS tex")
    )


def test_agent_gets_the_asta_skills():
    command = _devcontainer()["postCreateCommand"]
    assert "if command -v skills" in command
    assert "skills add /opt/asta-plugins" in command
    assert "npx --yes skills@1.5.0 add /opt/asta-plugins" in command


def test_skills_cli_is_pinned_in_the_image():
    package = json.loads(SKILLS_PACKAGE.read_text())
    lock = json.loads(SKILLS_LOCK.read_text())
    version = package["dependencies"]["skills"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert lock["packages"]["node_modules/skills"]["version"] == version
    dockerfile = DOCKERFILE.read_text()
    assert "npm ci --prefix /opt/skills-cli" in dockerfile
    assert "--engine-strict" in dockerfile
    assert "node_modules/.bin/skills /usr/local/bin/skills" in dockerfile


def _packages(text: str) -> set[str]:
    return set(re.findall(r"\b(?:latex\w*|texlive-[\w-]+|biber|poppler-utils)\b", text))


def test_tex_image_matches_ci_paper_lane():
    dockerfile = DOCKERFILE.read_text()
    tex_stage = dockerfile.split("FROM asta AS tex", 1)[1].split("\nFROM ", 1)[0]
    tex_stage = "\n".join(
        line for line in tex_stage.splitlines() if not line.startswith("LABEL ")
    )
    if not WORKFLOW.exists():
        pytest.skip("Paper preview workflow is not present yet")
    workflow = WORKFLOW.read_text()
    if "- name: Build paper preview" not in workflow:
        pytest.skip("Paper preview lane is not present yet")
    assert _packages(tex_stage) >= {
        "latexmk",
        "biber",
        "texlive-luatex",
        "texlive-xetex",
        "texlive-plain-generic",
    }
    lane = workflow.split("- name: Build paper preview", 1)[1].split(
        "\n      - name:", 1
    )[0]
    lane = lane.split("apt-get install -y --no-install-recommends", 1)[1].split(
        "; then", 1
    )[0]
    assert _packages(tex_stage) == _packages(lane)


def test_codespaces_login_persistence_ships_in_the_image() -> None:
    assert "asta-auth" not in json.dumps(_devcontainer())
    for stage in DOCKERFILE.read_text().split("\nFROM ")[:2]:
        label = re.search(r"^LABEL devcontainer\.metadata='(.+)'$", stage, re.M)
        assert label, "asta and tex stages must carry devcontainer.metadata"
        hooks = [m.get("postCreateCommand") for m in json.loads(label.group(1))]
        assert "asta-persist-auth" in hooks
    assert "COPY docker/asta-persist-auth /usr/local/bin/" in DOCKERFILE.read_text()
