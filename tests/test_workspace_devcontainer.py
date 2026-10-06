"""Static checks that keep the workspace dev container a working Codespaces surface."""

import json
import os
import re
import socket
import subprocess
import sys
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
    assert "latex-workshop" not in "".join(
        s for s in stages if not s.startswith("asta AS tex")
    )


def test_agent_gets_the_asta_skills():
    assert "skills@latest add /opt/asta-plugins" in _devcontainer()["postCreateCommand"]


def _packages(text: str) -> set[str]:
    return set(
        re.findall(
            r"\b(?:latexmk|latexdiff|latexml|texlive-[\w-]+|biber|poppler-utils)\b",
            text,
        )
    )


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


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX sh")
@pytest.mark.parametrize(
    ("codespace_name", "forwarding_domain", "expected_url"),
    [
        ("", "", "http://localhost:4848/"),
        ("example-space", "", "https://example-space-4848.app.github.dev/"),
        ("example-space", "example.test", "https://example-space-4848.example.test/"),
    ],
)
@pytest.mark.parametrize(
    ("port_open", "project", "start_status", "expected_status", "expected_calls"),
    [
        (True, "managed", 0, 0, ""),
        (False, "managed", 0, 0, "make preview\n"),
        (False, "managed", 2, 1, "make preview\n"),
        (False, "managed", 137, 1, "make preview\n"),
        (False, "make-only", 0, 0, "make preview\n"),
        (False, "quarto", 0, 0, "quarto preview --no-browser --port 4848\n"),
        (False, "quarto", 2, 1, "quarto preview --no-browser --port 4848\n"),
        (False, "empty", 0, 0, ""),
    ],
)
def test_preview_startup_preserves_prerequisites_and_reports_errors(
    tmp_path,
    port_open,
    project,
    start_status,
    expected_status,
    expected_calls,
    codespace_name,
    forwarding_domain,
    expected_url,
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    for name in ("python3", "make", "quarto"):
        script = bin_dir / name
        if name == "python3":
            body = f'printf "%s\\n" "$*" > "$PREVIEW_PROBE"\nexit {0 if port_open else 1}\n'
        else:
            body = (
                f'printf "%s\\n" "{name} $*" >> "$PREVIEW_CALLS"\nexit {start_status}\n'
            )
        script.write_text("#!/bin/sh\n" + body)
        script.chmod(0o755)
    if project in ("managed", "make-only"):
        (tmp_path / "Makefile").touch()
    if project in ("managed", "quarto"):
        (tmp_path / "_quarto.yml").touch()
    env = {
        "PATH": f"{bin_dir}:{os.defpath}",
        "PREVIEW_CALLS": str(calls),
        "PREVIEW_PROBE": str(tmp_path / "probe"),
        "CODESPACE_NAME": codespace_name,
        "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN": forwarding_domain,
    }
    result = subprocess.run(
        ["sh", "-c", _devcontainer()["postAttachCommand"]["preview"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == expected_status
    assert (calls.read_text() if calls.exists() else "") == expected_calls
    assert f"Quarto preview: {expected_url}" in result.stdout
    assert (tmp_path / "probe").read_text().rstrip() == (
        '-c import socket; socket.create_connection(("127.0.0.1", 4848), 2).close()'
    )
    assert ("Quarto preview failed" in result.stderr) == (expected_status != 0)


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX sh")
def test_preview_reuses_listening_server_without_waiting_for_http(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").symlink_to(sys.executable)
    calls = tmp_path / "calls"
    for name in ("make", "quarto"):
        script = bin_dir / name
        script.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$PREVIEW_CALLS"\nexit 2\n'
        )
        script.chmod(0o755)
    (tmp_path / "Makefile").touch()
    (tmp_path / "_quarto.yml").touch()

    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 4848))
        listener.listen()
        # The port accepts connections but never sends an HTTP response.
        result = subprocess.run(
            ["sh", "-c", _devcontainer()["postAttachCommand"]["preview"]],
            cwd=tmp_path,
            env={
                "PATH": f"{bin_dir}:{os.defpath}",
                "PREVIEW_CALLS": str(calls),
            },
            capture_output=True,
            text=True,
            timeout=5,
        )

    assert result.returncode == 0, result.stderr
    assert not calls.exists(), "must not start another preview on an occupied port"
