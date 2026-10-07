"""Tests for `asta workspace preview`."""

import io
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

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
    assert result.output.count("Preview URL (once serving)") == 1


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
        json.dumps({"pid": pid or 123456, "project": str(owner or project.resolve())})
    )


def test_live_record_reuses_preview(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path)
    monkeypatch.setattr(workspace_module.os, "kill", lambda pid, signum: None)
    monkeypatch.setattr(workspace_module, "preview_running", lambda: True)
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "Preview already running" in result.output
    assert ran.calls == []
    assert (tmp_path / workspace_module.PREVIEW_STATE).exists()


def test_starting_record_reports_retry_without_launching(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path)
    monkeypatch.setattr(workspace_module.os, "kill", lambda pid, signum: None)
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


def test_record_with_this_launchers_pid_is_replaced(tmp_path, ran):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path, pid=os.getpid())
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert len(ran.calls) == 1


def test_permission_denied_pid_is_not_reused(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path)

    def forbidden(pid, signum):
        raise PermissionError

    monkeypatch.setattr(workspace_module.os, "kill", forbidden)
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
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


def test_codespaces_default_domain(tmp_path, ran, monkeypatch):
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    monkeypatch.setenv("CODESPACE_NAME", "example")
    monkeypatch.delenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", raising=False)
    assert "https://example-4848.app.github.dev/" in invoke(tmp_path).output


def test_nothing_to_preview(tmp_path, ran):
    result = invoke(tmp_path)
    assert result.exit_code == 0
    assert "nothing to preview" in result.output
    assert not ran.calls
    assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()


def test_nonexistent_project_is_rejected(tmp_path, ran):
    result = invoke(tmp_path / "missing")
    assert result.exit_code != 0
    assert "does not exist" in result.output
    assert not ran.calls


@pytest.mark.parametrize("returncode", [-signal.SIGINT, 130])
def test_interrupted_preview_exits_130(tmp_path, ran, returncode):
    (tmp_path / "Makefile").write_text("preview:\n")
    ran.returncode = returncode
    assert invoke(tmp_path).exit_code == 130
    assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()


def test_missing_quarto_reports_error_and_cleans_state(tmp_path, ran, monkeypatch):
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    monkeypatch.setattr(workspace_module.shutil, "which", lambda name: None)
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "quarto is not installed" in result.output
    assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX signals")
def test_second_stop_signals_do_not_interrupt_state_cleanup(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    unlink = Path.unlink
    handlers = {
        s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    }

    def interrupted_unlink(path, **kwargs):
        if path == tmp_path / workspace_module.PREVIEW_STATE:
            for signum in handlers:
                os.kill(os.getpid(), signum)
        unlink(path, **kwargs)

    monkeypatch.setattr(Path, "unlink", interrupted_unlink)
    ran.returncode = 130
    assert invoke(tmp_path).exit_code == 130
    assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()
    assert all(signal.getsignal(s) == handler for s, handler in handlers.items())


@pytest.mark.parametrize(
    "diagnostic,missing",
    [
        (b"make: *** No rule to make target `preview'.  Stop.\n", True),
        (b"gmake: *** No rule to make target 'preview'.  Stop.\n", True),
        (b"/usr/bin/make: *** No rule to make target 'preview'.  Stop.\n", True),
        (b"make[1]: *** No rule to make target 'preview'.  Stop.\n", False),
        (
            b"make: *** No rule to make target 'absent', needed by 'preview'.  Stop.\n",
            False,
        ),
        (
            b"make: *** No rule to make target 'preview'.  Stop.\nmake: *** [preview] Error 2\n",
            False,
        ),
    ],
)
def test_make_diagnostic_compatibility(tmp_path, monkeypatch, diagnostic, missing):
    process = SimpleNamespace(stderr=io.BytesIO(diagnostic), wait=lambda: 2)
    monkeypatch.setattr(
        workspace_module, "preview_process", lambda *a, **kw: nullcontext(process)
    )
    assert workspace_module.run_make_preview(tmp_path) == (2, missing)


@pytest.mark.skipif(not shutil.which("make"), reason="requires GNU Make")
def test_real_make_does_not_inherit_parent_make_controls(tmp_path, monkeypatch):
    (tmp_path / "injected.mk").write_text("preview:\n\t@false\n")
    for name, value in {
        "MAKEFLAGS": "-n -w",
        "MFLAGS": "-i",
        "GNUMAKEFLAGS": "-k",
        "MAKELEVEL": "7",
        "MAKEFILES": str(tmp_path / "injected.mk"),
        "PROJECT_SETTING": "kept",
    }.items():
        monkeypatch.setenv(name, value)
    (tmp_path / "Makefile").write_text(
        "preview:\n\t@printf '%s' \"$$PROJECT_SETTING\" > ran\n"
    )
    assert workspace_module.run_make_preview(tmp_path) == (0, False)
    assert (tmp_path / "ran").read_text() == "kept"
    (tmp_path / "Makefile").write_text("other:\n\t@true\n")
    assert workspace_module.run_make_preview(tmp_path) == (2, True)


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
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    server = tmp_path / "server.py"
    server.write_text(
        f"""import http.server, os
from pathlib import Path
Path('server.pid').write_text(str(os.getpid()))
http.server.HTTPServer(('127.0.0.1', {port}), http.server.SimpleHTTPRequestHandler).serve_forever()
"""
    )
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    # A fake Quarto isolates CLI lifecycle behavior from the rendering toolchain.
    quarto = tmp_path / "quarto"
    quarto.write_text(f"#!/bin/sh\nexec {sys.executable} {server}\n")
    quarto.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    command = [
        sys.executable,
        "-c",
        f"from asta.commands import workspace; workspace.PREVIEW_PORT = {port}; "
        "from asta.cli import cli; cli()",
        "workspace",
        "preview",
        "--project",
        str(tmp_path),
    ]

    def listening():
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
        except OSError:
            return False
        return True

    process = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not (tmp_path / "server.pid").exists() or not listening():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.05)
        rerun = subprocess.run(
            command,
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
        assert not listening()
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=6)


def test_live_socket_is_detected(monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        monkeypatch.setattr(workspace_module, "PREVIEW_PORT", listener.getsockname()[1])
        listener.listen()
        assert workspace_module.preview_running()
