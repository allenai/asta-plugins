"""Tests for `asta workspace preview`."""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from asta.cli import cli
from asta.commands import workspace as workspace_module


class Ran:
    def __init__(self):
        self.returncode = 0
        self.no_rule = False
        self.calls: list[list[str]] = []
        self.state_during_run = None

    def _record(self, command, project):
        self.calls.append(command)
        state = Path(project) / workspace_module.PREVIEW_STATE
        self.state_during_run = (
            json.loads(state.read_text()) if state.exists() else None
        )

    def make(self, project):
        self._record(["make", "preview"], project)
        return (2, True) if self.no_rule else (self.returncode, False)

    def run(self, command, project):
        self._record(command, project)
        return self.returncode


@pytest.fixture
def ran(monkeypatch):
    runner = Ran()
    monkeypatch.setattr(workspace_module, "run_make_preview", runner.make)
    monkeypatch.setattr(workspace_module, "run_preview", runner.run)
    monkeypatch.setattr(workspace_module, "preview_running", lambda: False)
    monkeypatch.setattr(workspace_module.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.delenv("CODESPACE_NAME", raising=False)
    return runner


def invoke(project: Path):
    return CliRunner().invoke(cli, ["workspace", "preview", "--project", str(project)])


QUARTO = ["quarto", "preview", "--no-browser", "--port", "4848"]


@pytest.mark.parametrize("makefile_name", ["GNUmakefile", "makefile", "Makefile"])
def test_makefile_runs_make_preview(tmp_path, ran, makefile_name):
    (tmp_path / makefile_name).write_text("preview:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "Preview URL (once serving): http://localhost:4848/" in result.output
    assert ran.calls == [["make", "preview"]]


def test_quarto_only_project(tmp_path, ran):
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    assert invoke(tmp_path).exit_code == 0
    assert ran.calls == [QUARTO]


def test_missing_preview_rule_falls_back_to_quarto(tmp_path, ran):
    (tmp_path / "Makefile").write_text("other:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    ran.no_rule = True
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert ran.calls == [["make", "preview"], QUARTO]


def test_missing_make_falls_back_to_quarto(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    monkeypatch.setattr(
        workspace_module.shutil,
        "which",
        lambda name: None if name == "make" else "/bin/quarto",
    )
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "make is not installed; using quarto preview" in result.output
    assert "Preview URL (once serving)" in result.output
    assert ran.calls == [QUARTO]


def test_preview_can_run_from_a_worker_thread(tmp_path, ran):
    (tmp_path / "Makefile").write_text("preview:\n")
    results = []
    worker = threading.Thread(target=lambda: results.append(invoke(tmp_path)))
    worker.start()
    worker.join(5)
    assert not worker.is_alive()
    assert results[0].exit_code == 0, results[0].output
    assert ran.calls == [["make", "preview"]]


def test_missing_preview_rule_without_quarto_fails(tmp_path, ran):
    (tmp_path / "Makefile").write_text("other:\n")
    ran.no_rule = True
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "make preview failed (exit 2)" in result.output


def test_state_records_this_project_while_running_and_is_removed(tmp_path, ran):
    (tmp_path / "Makefile").write_text("preview:\n")
    assert invoke(tmp_path).exit_code == 0
    assert ran.state_during_run == {
        "pid": os.getpid(),
        "project": str(tmp_path.resolve()),
    }
    assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()


def write_state(project, pid=None, owner=None):
    state = project / workspace_module.PREVIEW_STATE
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps(
            {"pid": pid or os.getpid(), "project": str(owner or project.resolve())}
        )
    )


def test_live_record_reuses_preview(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path)
    monkeypatch.setattr(workspace_module, "preview_running", lambda: True)
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "Preview already running" in result.output
    assert ran.calls == []
    assert (tmp_path / workspace_module.PREVIEW_STATE).exists()


def test_starting_record_reports_retry_without_launching(tmp_path, ran):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path)
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "still starting" in result.output
    assert ran.calls == []


@pytest.mark.parametrize(
    "record", ["bad json", "[]", "{}", '{"pid": -1, "project": "wrong"}']
)
def test_invalid_record_is_replaced(tmp_path, ran, record):
    (tmp_path / "Makefile").write_text("preview:\n")
    state = tmp_path / workspace_module.PREVIEW_STATE
    state.parent.mkdir(parents=True)
    state.write_text(record)
    assert invoke(tmp_path).exit_code == 0
    assert ran.state_during_run["pid"] == os.getpid()
    assert not state.exists()


def test_dead_record_is_replaced(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path, pid=123456)

    def dead(pid, signal_number):
        assert (pid, signal_number) == (123456, 0)
        raise ProcessLookupError

    monkeypatch.setattr(workspace_module.os, "kill", dead)
    assert invoke(tmp_path).exit_code == 0
    assert len(ran.calls) == 1


def test_occupied_port_with_no_live_record_fails(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    monkeypatch.setattr(workspace_module, "preview_running", lambda: True)
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "in use by another process" in result.output
    assert ran.calls == []


def test_foreign_project_record_does_not_allow_reuse(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path, owner=tmp_path / "other")
    monkeypatch.setattr(workspace_module, "preview_running", lambda: True)
    assert invoke(tmp_path).exit_code != 0
    assert ran.calls == []


def test_failed_launch_removes_record(tmp_path, ran):
    (tmp_path / "Makefile").write_text("preview:\n")
    ran.returncode = 2
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "make preview failed" in result.output
    assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()


def test_codespaces_link(tmp_path, ran, monkeypatch):
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    monkeypatch.setenv("CODESPACE_NAME", "example")
    monkeypatch.setenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
    assert "https://example-4848.app.github.dev/" in invoke(tmp_path).output


@pytest.mark.skipif(not shutil.which("make"), reason="requires GNU Make")
@pytest.mark.parametrize(
    "makefile,missing",
    [
        ("other:\n\t@true\n", True),
        ("preview: absent\n", False),
        ("preview:\n\t@false\n", False),
        (".PHONY: preview\npreview:\n\t@true\n", False),
    ],
)
def test_real_make_fallback_only_for_missing_preview(tmp_path, makefile, missing):
    (tmp_path / "Makefile").write_text(makefile)
    returncode, no_rule = workspace_module.run_make_preview(tmp_path)
    assert no_rule is missing
    assert returncode == (0 if "@true" in makefile and "preview:" in makefile else 2)


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
@pytest.mark.parametrize("stop_signal", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_real_start_reuse_and_shutdown(tmp_path, stop_signal):
    server = tmp_path / "server.py"
    server.write_text(
        "import http.server, os\nfrom pathlib import Path\nPath('server.pid').write_text(str(os.getpid()))\nhttp.server.HTTPServer(('127.0.0.1', 4848), http.server.SimpleHTTPRequestHandler).serve_forever()\n"
    )
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    # A fake Quarto isolates CLI lifecycle behavior from the rendering toolchain.
    quarto = tmp_path / "quarto"
    quarto.write_text(f"#!/bin/sh\nexec {sys.executable} {server}\n")
    quarto.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "asta.cli",
            "workspace",
            "preview",
            "--project",
            str(tmp_path),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while (
            not (tmp_path / "server.pid").exists()
            or not workspace_module.preview_running()
        ):
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.05)
        rerun = subprocess.run(
            [
                sys.executable,
                "-m",
                "asta.cli",
                "workspace",
                "preview",
                "--project",
                str(tmp_path),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert rerun.returncode == 0, rerun.stderr
        assert "Preview already running" in rerun.stdout
        process.send_signal(stop_signal)
        assert process.wait(timeout=6) == 128 + stop_signal
        assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()
        assert not workspace_module.preview_running()
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=6)


def test_live_socket_is_detected():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 4848))
        listener.listen()
        assert workspace_module.preview_running()
