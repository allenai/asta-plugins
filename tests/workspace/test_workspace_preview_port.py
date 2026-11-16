"""`make preview` picks its port: ASTA_PREVIEW_PORT, 4848 in Codespaces, else the first free one."""

import os
import shutil
import socket
import stat
import subprocess
from pathlib import Path

import pytest

ASSETS = Path(__file__).parents[2] / "plugins/asta-tools/skills/workspace/assets"

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="needs make")


@pytest.fixture(params=["workspace.mk", "Makefile"])
def project(request, tmp_path):
    # The managed rules and the standalone Makefile share the recipe
    shutil.copy(ASSETS / request.param, tmp_path / "rules.mk")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    quarto = bin_dir / "quarto"
    quarto.write_text('#!/bin/sh\necho "quarto $*"\n')
    quarto.chmod(quarto.stat().st_mode | stat.S_IEXEC)
    return tmp_path


def preview(project, **env):
    run_env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("CODESPACE_NAME", "ASTA_PREVIEW_PORT", "MAKEFLAGS")
    }
    run_env["PATH"] = f"{project / 'bin'}{os.pathsep}{run_env['PATH']}"
    run_env.update(env)
    result = subprocess.run(
        [
            "make",
            "-f",
            "rules.mk",
            "-o",
            "workspace-assets",
            "-o",
            "workspace-viewers",
            "preview",
        ],
        cwd=project,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    line = next(x for x in result.stdout.splitlines() if x.startswith("quarto "))
    port = int(line.split("--port ")[1])
    assert f"preview: http://localhost:{port}/" in result.stdout
    return port


def listening(port):
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) == 0


def test_a_taken_port_is_skipped(project):
    holders = []
    try:
        for port in (4848, 4850):
            if not listening(port):
                held = socket.socket()
                held.bind(("127.0.0.1", port))
                held.listen(1)
                holders.append(held)
        port = preview(project)
        assert port not in (4848, 4849, 4850)
        assert not listening(port)
    finally:
        for held in holders:
            held.close()


def test_an_explicit_port_wins(project):
    assert preview(project, ASTA_PREVIEW_PORT="5123") == 5123


def test_codespaces_keeps_the_forwarded_port(project):
    held = None
    if not listening(4848):
        held = socket.socket()
        held.bind(("127.0.0.1", 4848))
        held.listen(1)
    try:
        assert preview(project, CODESPACE_NAME="example") == 4848
    finally:
        if held:
            held.close()
