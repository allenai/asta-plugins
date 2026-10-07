"""Tests for `asta workspace preview`."""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from click.testing import CliRunner
from filelock import FileLock

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

    def run(self, command, cwd, check, **kwargs):
        self._record(command, cwd)
        return type("Result", (), {"returncode": self.returncode})()


@pytest.fixture
def ran(monkeypatch):
    runner = Ran()
    monkeypatch.setattr(workspace_module, "run_make_preview", runner.make)
    monkeypatch.setattr(workspace_module.subprocess, "run", runner.run)
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
    assert "Preview: http://localhost:4848/" in result.output
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


def write_state(project: Path, pid: int, path: Path | None = None):
    state = project / workspace_module.PREVIEW_STATE
    state.parent.mkdir(exist_ok=True)
    state.write_text(
        json.dumps({"pid": pid, "project": str(path or project.resolve())})
    )


def test_own_running_preview_is_reused(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path, os.getpid())
    monkeypatch.setattr(workspace_module, "preview_running", lambda: True)
    with FileLock(tmp_path / workspace_module.PREVIEW_LOCK):
        result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "Preview already running: http://localhost:4848/" in result.output
    assert ran.calls == []


def test_starting_preview_does_not_claim_success_before_port_listens(
    tmp_path, ran, monkeypatch
):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path, os.getpid())
    monkeypatch.setattr(workspace_module, "PREVIEW_START_TIMEOUT", 0)
    with FileLock(tmp_path / workspace_module.PREVIEW_LOCK):
        result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "still starting or not listening" in result.output
    assert "already running" not in result.output
    assert ran.calls == []


def test_reattach_waits_for_owned_preview_to_listen(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path, os.getpid())
    probes = iter([False, True])
    monkeypatch.setattr(workspace_module, "preview_running", lambda: next(probes))
    monkeypatch.setattr(workspace_module.time, "sleep", lambda _: None)
    with FileLock(tmp_path / workspace_module.PREVIEW_LOCK):
        result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "already running" in result.output
    assert ran.calls == []


def test_live_pid_without_launcher_lock_does_not_prove_ownership(tmp_path, ran):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path, os.getpid())
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "already running" not in result.output
    assert ran.calls == [["make", "preview"]]


def dead_pid() -> int:
    pid = 2**22 + 12345
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    return pid


def test_stale_state_is_replaced(tmp_path, ran):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path, dead_pid())
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert ran.calls == [["make", "preview"]]
    assert ran.state_during_run["pid"] == os.getpid()


@pytest.mark.parametrize(
    "state", ["stale", "live-pid", "other-project", "corrupt", "none"]
)
def test_foreign_listener_is_rejected(tmp_path, ran, monkeypatch, state):
    (tmp_path / "Makefile").write_text("preview:\n")
    if state == "stale":
        write_state(tmp_path, dead_pid())
    elif state == "live-pid":
        write_state(tmp_path, os.getpid())
    elif state == "other-project":
        write_state(tmp_path, os.getpid(), tmp_path / "elsewhere")
    elif state == "corrupt":
        (tmp_path / ".asta").mkdir()
        (tmp_path / workspace_module.PREVIEW_STATE).write_text("{")
    monkeypatch.setattr(workspace_module, "preview_running", lambda: True)
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "Port 4848 is in use by another process" in result.output
    assert "Preview:" not in result.output
    assert ran.calls == []


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_preview_probe_detects_a_listening_socket(monkeypatch, host):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        server = socket.socket(family)
        server.bind((host, 0))
    except OSError:
        pytest.skip(f"{host} unavailable")
    with server:
        server.listen()
        monkeypatch.setattr(workspace_module, "PREVIEW_PORT", server.getsockname()[1])
        assert workspace_module.preview_running()


def test_make_env_drops_caller_make_controls(monkeypatch):
    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    for name in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "GNUMAKEFLAGS", "MAKEFILES"):
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("PROJECT_VAR", "kept")
    env = workspace_module.make_preview_env()
    assert (
        not {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "GNUMAKEFLAGS", "MAKEFILES"}
        & env.keys()
    )
    assert env["PROJECT_VAR"] == "kept"
    assert env["LC_ALL"] == "C"


def test_codespaces_url(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    monkeypatch.setenv("CODESPACE_NAME", "demo")
    monkeypatch.delenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", raising=False)
    assert "https://demo-4848.app.github.dev/" in invoke(tmp_path).output


@pytest.mark.parametrize(
    ("project_file", "command"),
    [("Makefile", "make preview"), ("_quarto.yml", " ".join(QUARTO))],
)
def test_failure_is_reported(tmp_path, ran, project_file, command):
    (tmp_path / project_file).touch()
    ran.returncode = 2
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert f"{command} failed (exit 2)" in result.output
    assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()


@pytest.mark.parametrize("returncode", [-signal.SIGINT, 130])
def test_interrupted_preview_exits_cleanly(tmp_path, ran, returncode):
    (tmp_path / "Makefile").write_text("preview:\n")
    ran.returncode = returncode
    result = invoke(tmp_path)
    assert result.exit_code == 130, result.output
    assert "failed" not in result.output


def test_keyboard_interrupt_exits_cleanly_and_clears_state(tmp_path, ran, monkeypatch):
    (tmp_path / "_quarto.yml").write_text("project: {}\n")

    def run(command, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(workspace_module.subprocess, "run", run)
    result = invoke(tmp_path)
    assert result.exit_code == 130, result.output
    assert "Aborted" not in result.output
    assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()


def test_nothing_to_preview(tmp_path, ran):
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "nothing to preview" in result.output
    assert ran.calls == []


def test_nonexistent_project_is_rejected(tmp_path, ran):
    result = invoke(tmp_path / "missing-project")
    assert result.exit_code != 0
    assert "does not exist" in result.output
    assert ran.calls == []


@pytest.mark.parametrize("project_file", ["Makefile", "_quarto.yml"])
def test_missing_executable_does_not_advertise_a_url(
    tmp_path, ran, monkeypatch, project_file
):
    (tmp_path / project_file).touch()
    monkeypatch.setattr(workspace_module.shutil, "which", lambda name: None)
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "is not installed" in result.output
    assert "Preview:" not in result.output
    assert ran.calls == []
    assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()


@pytest.fixture
def real_make(monkeypatch):
    if shutil.which("make") is None:
        pytest.skip("requires GNU Make")
    monkeypatch.setattr(workspace_module, "preview_running", lambda: False)
    monkeypatch.delenv("CODESPACE_NAME", raising=False)
    actual_which = shutil.which
    monkeypatch.setattr(
        workspace_module.shutil,
        "which",
        lambda name: "/bin/quarto" if name == "quarto" else actual_which(name),
    )
    calls = []
    actual_run = subprocess.run

    def run(command, **kwargs):
        if command[0] == "quarto":
            calls.append(command)
            return subprocess.CompletedProcess(command, 0)
        return actual_run(command, **kwargs)

    monkeypatch.setattr(workspace_module.subprocess, "run", run)
    return calls


@pytest.mark.parametrize("artifact", ["file", "directory"])
def test_real_make_preview_artifact_cannot_silently_succeed(
    tmp_path, real_make, artifact
):
    (tmp_path / "Makefile").write_text("check:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    if artifact == "file":
        (tmp_path / "preview").touch()
    else:
        (tmp_path / "preview").mkdir()
    result = invoke(tmp_path)
    assert result.exit_code != 0, result.output
    assert "exited without starting a preview" in result.output
    assert real_make == []


@pytest.mark.parametrize("nested", ["$(MAKE)", "env -u MAKELEVEL $(MAKE)"])
def test_nested_make_missing_preview_does_not_hide_recipe_failure(
    tmp_path, real_make, nested
):
    (tmp_path / "Makefile").write_text(f"preview:\n\t@{nested} -C child preview\n")
    (tmp_path / "child").mkdir()
    (tmp_path / "child/Makefile").write_text("check:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    result = invoke(tmp_path)
    assert result.exit_code != 0, result.output
    assert "make preview failed (exit 2)" in result.output
    assert real_make == []


@pytest.mark.parametrize("makefile_name", ["GNUmakefile", "makefile", "Makefile"])
def test_real_make_missing_rule_falls_back(tmp_path, real_make, makefile_name):
    (tmp_path / makefile_name).write_text("check:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert real_make == [QUARTO]


def test_real_make_included_custom_preview_takes_priority(tmp_path, real_make):
    (tmp_path / "Makefile").write_text("include rules.mk\n")
    (tmp_path / "rules.mk").write_text("preview:\n\t@echo custom > calls\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert (tmp_path / "calls").read_text() == "custom\n"
    assert real_make == []


def test_real_make_fallback_survives_long_parse_output(tmp_path, real_make):
    (tmp_path / "Makefile").write_text("$(warning " + "x" * 5000 + ")\ncheck:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert real_make == [QUARTO]


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
@pytest.mark.parametrize("serves", [True, False])
def test_real_launcher_reattach_checks_lock_and_listener(tmp_path, monkeypatch, serves):
    if shutil.which("make") is None:
        pytest.skip("requires GNU Make")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    monkeypatch.setattr(workspace_module, "PREVIEW_PORT", port)
    monkeypatch.setattr(workspace_module, "PREVIEW_START_TIMEOUT", 0.5)
    (tmp_path / "server.py").write_text(
        "from pathlib import Path\n"
        "import socket, time\n"
        "with Path('launches').open('a') as log: log.write('start\\n')\n"
        "time.sleep(0.2)\n"
        "server = socket.socket()\n"
        + (f"server.bind(('127.0.0.1', {port})); server.listen()\n" if serves else "")
        + "time.sleep(60)\n"
    )
    (tmp_path / "Makefile").write_text(f"preview:\n\t@{sys.executable} server.py\n")
    script = (
        "from asta.cli import cli\n"
        "from asta.commands import workspace\n"
        f"workspace.PREVIEW_PORT = {port}\n"
        "cli()\n"
    )
    with (tmp_path / "launcher.log").open("w+") as log:
        launcher = subprocess.Popen(
            [sys.executable, "-c", script, "workspace", "preview"],
            cwd=tmp_path,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 5
            while not (tmp_path / "launches").exists():
                assert launcher.poll() is None
                assert time.monotonic() < deadline
                time.sleep(0.01)
            result = invoke(tmp_path)
            assert result.exit_code == (0 if serves else 1), result.output
            assert ("already running" in result.output) == serves
            assert (tmp_path / "launches").read_text() == "start\n"
        finally:
            os.killpg(launcher.pid, signal.SIGKILL)
            launcher.wait(timeout=5)
        # A killed owner leaves JSON, but the kernel releases its ownership lock.
        assert (tmp_path / workspace_module.PREVIEW_STATE).exists()
        with FileLock(tmp_path / workspace_module.PREVIEW_LOCK, timeout=0):
            pass
