"""Static checks that keep the workspace dev container a working Codespaces surface."""

import json
import os
import re
import subprocess
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
    assert "devcontainer.metadata" not in "".join(
        s for s in stages if not s.startswith("asta AS tex")
    )


def test_agent_gets_the_asta_skills():
    assert "skills@latest add /opt/asta-plugins" in _devcontainer()["postCreateCommand"]


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


def test_codespaces_persists_asta_login() -> None:
    cmd = _devcontainer()["postCreateCommand"]
    assert "CODESPACES" in cmd
    assert "cp -an" in cmd
    assert "ln -sfnT /workspaces/.asta-auth" in cmd
    assert cmd.index("ln -sfnT") < cmd.index("skills@latest add")


@pytest.mark.parametrize("conflict", [False, True])
def test_codespaces_migration_preserves_credentials(tmp_path: Path, conflict: bool) -> None:
    command = _devcontainer()["postCreateCommand"]
    persisted = tmp_path / "persisted"
    persisted.mkdir()
    (persisted / "login").write_text("old")
    (persisted / "refresh").write_text("keep")
    home = tmp_path / "home"
    source = home / ".config/asta-cli"
    source.mkdir(parents=True)
    (source / "login").write_text("new" if conflict else "old")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    installer = bin_dir / "npx"
    installer.write_text("#!/bin/sh\nexit 0\n")
    installer.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "CODESPACES": "true",
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        ["sh", "-c", command.replace("/workspaces/.asta-auth", str(persisted))],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (persisted / "refresh").read_text() == "keep"
    assert source.is_symlink() is not conflict
    assert (source / "login").read_text() == ("new" if conflict else "old")
