"""Static checks that keep the workspace dev container a working Codespaces surface."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "plugins/asta-tools/skills/workspace/assets/devcontainer.json"
DOCKERFILE = ROOT / "Dockerfile"
WORKFLOW = ROOT / ".github/workflows/workspace-quarto-site.yml"


def _devcontainer() -> dict:
    return json.loads(ASSET.read_text())


def test_asta_token_is_a_codespaces_secret():
    config = _devcontainer()
    assert "ASTA_TOKEN" in config.get("secrets", {})
    # ${localEnv:...} is empty in Codespaces and would blank the secret.
    assert "localEnv:ASTA_TOKEN" not in json.dumps(config)


def test_preview_port_opens_in_simple_browser():
    config = _devcontainer()
    assert 4848 in config["forwardPorts"]
    assert config["portsAttributes"]["4848"]["onAutoForward"] == "openPreview"
    assert (
        "quarto preview --no-browser --port 4848"
        in config["postAttachCommand"]["preview"]
    )


def test_quarto_and_latex_workshop_extensions_listed():
    extensions = _devcontainer()["customizations"]["vscode"]["extensions"]
    assert "quarto.quarto" in extensions
    assert "james-yu.latex-workshop" in extensions


def test_agent_gets_the_asta_skills():
    assert "skills@1.7.0 add /opt/asta-plugins" in _devcontainer()["postCreateCommand"]


def _packages(text: str) -> set[str]:
    return set(re.findall(r"\b(?:latex\w*|texlive-[\w-]+|biber|poppler-utils)\b", text))


def test_tex_image_matches_ci_paper_lane():
    dockerfile = DOCKERFILE.read_text()
    tex_stage = dockerfile.split("FROM asta AS tex", 1)[1].split("\nFROM ", 1)[0]
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
    }
    lane = workflow.split("- name: Build paper preview", 1)[1].split(
        "\n      - name:", 1
    )[0]
    lane = lane.split("apt-get install -y --no-install-recommends", 1)[1].split(
        "; then", 1
    )[0]
    assert _packages(tex_stage) == _packages(lane)


def test_codespaces_persists_asta_login() -> None:
    cmd = _devcontainer()["postCreateCommand"]
    assert "CODESPACES" in cmd
    assert "cp -an" in cmd
    assert "ln -sfnT /workspaces/.asta-auth" in cmd
    assert cmd.index("ln -sfnT") < cmd.index("skills@1.7.0 add")
