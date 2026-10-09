"""Static checks that keep the workspace dev container a working Codespaces surface."""

import json
import os
import re
import subprocess
import sys
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
    assert config["postAttachCommand"]["preview"] == "exec asta workspace preview"


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


def test_tex_image_copies_upstream_full_instead_of_explicit_debian_tex_packages():
    dockerfile = DOCKERFILE.read_text()
    tex_stage = dockerfile.split("FROM asta AS tex", 1)[1].split("\nFROM ", 1)[0]
    assert "COPY --from=mirror.gcr.io/texlive/texlive:latest-full@sha256:" in tex_stage
    assert "grep -q 'TeX Live 2026'" in tex_stage
    # latexml still brings Debian's base TeX transitively.
    packages = re.search(
        r"apt-get install -y --no-install-recommends (.*?)&&", tex_stage, re.S
    )
    assert packages
    assert not any(name.startswith("texlive-") for name in packages.group(1).split())
    assert "latexml" in tex_stage


def test_codespaces_login_persistence_ships_in_the_image() -> None:
    assert "asta-auth" not in json.dumps(_devcontainer())
    for stage in DOCKERFILE.read_text().split("\nFROM ")[:2]:
        label = re.search(r"^LABEL devcontainer\.metadata='(.+)'$", stage, re.M)
        assert label, "asta and tex stages must carry devcontainer.metadata"
        hooks = [m.get("postCreateCommand") for m in json.loads(label.group(1))]
        assert "asta-persist-auth" in hooks
    assert "COPY docker/asta-persist-auth /usr/local/bin/" in DOCKERFILE.read_text()


def test_preview_probe_python_ships_in_both_images():
    dockerfile = DOCKERFILE.read_text()
    asta_stage = dockerfile.split("\nFROM ", 1)[0]
    packages = re.search(
        r"apt-get install -y --no-install-recommends (.*?)&&", asta_stage, re.S
    )
    assert packages and "python3" in packages.group(1).split()
    assert "FROM asta AS tex" in dockerfile


@pytest.mark.parametrize(
    ("fixture", "arguments"),
    [
        ("check-post-create.py", []),
        ("check-post-create.py", ["unknown"]),
        ("check-post-attach.py", ["--preview-command", "unknown"]),
    ],
)
def test_smoke_fixtures_reject_invalid_arguments(fixture, arguments):
    script = ROOT / "tests/fixtures/devcontainer-smoke" / fixture
    result = subprocess.run(
        [sys.executable, str(script), *arguments], capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX sh")
@pytest.mark.parametrize("status", [0, 2, 130, 143])
def test_attach_preserves_cli_exit_status(tmp_path, status):
    cli = tmp_path / "asta"
    cli.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*"\nexit {status}\n')
    cli.chmod(0o755)
    result = subprocess.run(
        ["sh", "-c", _devcontainer()["postAttachCommand"]["preview"]],
        cwd=tmp_path,
        env={"PATH": f"{tmp_path}:{os.defpath}"},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.stdout == "workspace preview\n"
    assert result.returncode == status


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX sh")
def test_attach_in_empty_project_exits_successfully(tmp_path):
    result = subprocess.run(
        ["sh", "-c", _devcontainer()["postAttachCommand"]["preview"]],
        cwd=tmp_path,
        env={"PATH": f"{Path(sys.executable).parent}:{os.defpath}"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "nothing to preview" in result.stdout
    assert not (tmp_path / ".asta").exists()
