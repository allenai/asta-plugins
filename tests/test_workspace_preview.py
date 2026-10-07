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
        "project": str(tmp_path.resolve()),
    }
    assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()


def write_state(project: Path, path: Path | None = None):
    state = project / workspace_module.PREVIEW_STATE
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"project": str(path or project.resolve())}))


def test_own_running_preview_is_reused(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path)
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
    write_state(tmp_path)
    monkeypatch.setattr(workspace_module, "PREVIEW_START_TIMEOUT", 0)
    with FileLock(tmp_path / workspace_module.PREVIEW_LOCK):
        result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "still starting or not listening" in result.output
    assert "already running" not in result.output
    assert ran.calls == []


def test_reattach_waits_for_owned_preview_to_listen(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path)
    probes = iter([False, True])
    monkeypatch.setattr(workspace_module, "preview_running", lambda: next(probes))
    monkeypatch.setattr(workspace_module.time, "sleep", lambda _: None)
    with FileLock(tmp_path / workspace_module.PREVIEW_LOCK):
        result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "already running" in result.output
    assert ran.calls == []


def test_state_without_launcher_lock_does_not_prove_ownership(tmp_path, ran):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path)
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "already running" not in result.output
    assert ran.calls == [["make", "preview"]]


def test_stale_state_is_replaced(tmp_path, ran):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path)
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert ran.calls == [["make", "preview"]]
    assert ran.state_during_run == {"project": str(tmp_path.resolve())}


@pytest.mark.parametrize("state", ["this-project", "other-project", "corrupt", "none"])
def test_foreign_listener_is_rejected(tmp_path, ran, monkeypatch, state):
    (tmp_path / "Makefile").write_text("preview:\n")
    if state == "this-project":
        write_state(tmp_path)
    elif state == "other-project":
        write_state(tmp_path, tmp_path / "elsewhere")
    elif state == "corrupt":
        (tmp_path / workspace_module.PREVIEW_STATE).parent.mkdir(parents=True)
        (tmp_path / workspace_module.PREVIEW_STATE).write_text("{")
    monkeypatch.setattr(workspace_module, "preview_running", lambda: True)
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "Port 4848 is in use by another process" in result.output
    assert "Preview URL" not in result.output
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
    assert "LC_ALL" not in env
    assert env["LC_CTYPE"] == "fr_FR.UTF-8"
    assert env["LC_COLLATE"] == "fr_FR.UTF-8"
    assert env["LC_MESSAGES"] == "C"
    assert env["LANGUAGE"] == "C"


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

    def run(command, project):
        raise KeyboardInterrupt

    monkeypatch.setattr(workspace_module, "run_preview", run)
    result = invoke(tmp_path)
    assert result.exit_code == 130, result.output
    assert "Aborted" not in result.output
    assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()


def test_interrupt_during_lock_acquisition_exits_cleanly(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")

    def acquire(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(workspace_module.FileLock, "acquire", acquire)
    result = invoke(tmp_path)
    assert result.exit_code == 130, result.output
    assert "Aborted" not in result.output
    assert ran.calls == []


def test_interrupt_during_reattach_preserves_owner_state(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path)
    state = (tmp_path / workspace_module.PREVIEW_STATE).read_bytes()

    def sleep(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(workspace_module.time, "sleep", sleep)
    with FileLock(tmp_path / workspace_module.PREVIEW_LOCK):
        result = invoke(tmp_path)
    assert result.exit_code == 130, result.output
    assert "Aborted" not in result.output
    assert (tmp_path / workspace_module.PREVIEW_STATE).read_bytes() == state
    assert ran.calls == []


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
    assert "Preview URL" not in result.output
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
    actual_run = workspace_module.run_preview

    def run(command, project):
        if command[0] == "quarto":
            calls.append(command)
            return 0
        return actual_run(command, project)

    monkeypatch.setattr(workspace_module, "run_preview", run)
    return calls


@pytest.mark.parametrize("artifact", ["file", "directory"])
def test_real_make_noop_retains_make_success(tmp_path, real_make, artifact):
    (tmp_path / "Makefile").write_text("check:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    if artifact == "file":
        (tmp_path / "preview").touch()
    else:
        (tmp_path / "preview").mkdir()
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert real_make == []
    assert "Preview URL (once serving)" in result.output
    assert "already running" not in result.output


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


def test_real_preview_ignores_caller_make_controls(tmp_path, real_make, monkeypatch):
    (tmp_path / "Makefile").write_text(
        "preview:\n\t@printf '%s' \"$$PROJECT_VAR\" > calls\n"
    )
    poison = tmp_path / "poison.mk"
    poison.write_text("$(error must not load caller MAKEFILES)\n")
    for name in ("MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS"):
        monkeypatch.setenv(name, "--just-print")
    monkeypatch.setenv("MAKEFILES", str(poison))
    monkeypatch.setenv("MAKELEVEL", "42")
    monkeypatch.setenv("PROJECT_VAR", "kept")
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert (tmp_path / "calls").read_text() == "kept"
    assert real_make == []


def test_real_recipe_retains_locale_encoding(tmp_path, real_make, monkeypatch):
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setenv("LC_CTYPE", "C")
    (tmp_path / "Makefile").write_text(
        "preview:\n\t@locale charmap > charset\n\t@locale > locale-env\n"
    )
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert (tmp_path / "charset").read_text().strip() == "UTF-8"
    assert "LC_MESSAGES=C" in (tmp_path / "locale-env").read_text()


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX PTYs")
def test_real_recipe_keeps_terminal_stderr(tmp_path, real_make, monkeypatch):
    output = io.BytesIO()

    class Terminal:
        buffer = output

        def isatty(self):
            return True

        def flush(self):
            pass

    monkeypatch.setattr(workspace_module.sys, "stderr", Terminal())
    (tmp_path / "Makefile").write_text(
        f"preview:\n\t@{sys.executable} -c "
        '"import os,sys;sys.stderr.write(str(os.isatty(2)))"\n'
    )
    assert workspace_module.run_make_preview(tmp_path) == (0, False)
    assert output.getvalue() == b"True"


@pytest.mark.parametrize("failure", ["write", "flush"])
def test_closed_stderr_does_not_block_real_recipe(tmp_path, real_make, failure):
    (tmp_path / "Makefile").write_text(
        f"preview:\n\t@{sys.executable} -c "
        "\"import sys;sys.stderr.write('x'*2000000)\"\n"
    )
    script = (
        "import sys\nfrom asta.commands import workspace\n"
        "class Closed:\n"
        " def isatty(self): return False\n"
        " @property\n def buffer(self): return self\n"
        f" def {failure}(self, *args): raise BrokenPipeError()\n"
        + (
            " def flush(self): pass\n"
            if failure == "write"
            else " def write(self, data): pass\n"
        )
        + "original_stderr = sys.stderr\nsys.stderr = Closed()\n"
        + f"try: assert workspace.run_make_preview(workspace.Path({str(tmp_path)!r})) == (0, False)\n"
        + "finally: sys.stderr = original_stderr\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, timeout=5
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX background recipes")
def test_background_parse_output_cannot_hide_make_diagnostic(tmp_path, real_make):
    (tmp_path / "Makefile").write_text(
        "$(shell (sleep 0.05; printf '%5000s\\n' extra >&2) >/dev/null &)\ncheck:\n"
    )
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert real_make == [QUARTO]


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX background recipes")
def test_undrained_make_stderr_does_not_enable_fallback(tmp_path, real_make):
    (tmp_path / "Makefile").write_text(
        "$(shell (sleep 1.5; echo trailing >&2) >/dev/null &)\ncheck:\n"
    )
    assert workspace_module.run_make_preview(tmp_path) == (2, False)


def test_existing_cache_ignore_covers_all_preview_state(tmp_path, real_make):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".asta/cache/\n")
    (tmp_path / "Makefile").write_text("preview:\n")
    assert invoke(tmp_path).exit_code == 0
    paths = [str(workspace_module.PREVIEW_LOCK), str(workspace_module.PREVIEW_STATE)]
    result = subprocess.run(
        ["git", "check-ignore", *paths], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout.splitlines() == paths


def test_legacy_pid_is_ignored_during_held_lock_reuse(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    write_state(tmp_path)
    (tmp_path / workspace_module.PREVIEW_STATE).write_text(
        json.dumps({"project": str(tmp_path.resolve()), "pid": os.getpid()})
    )
    monkeypatch.setattr(workspace_module, "preview_running", lambda: True)

    def forbidden(*args):
        raise AssertionError("PID signalling must not be used for ownership")

    monkeypatch.setattr(workspace_module.os, "kill", forbidden)
    with FileLock(tmp_path / workspace_module.PREVIEW_LOCK):
        assert invoke(tmp_path).exit_code == 0


def test_interrupted_project_lock_release_still_releases_port(
    tmp_path, ran, monkeypatch
):
    (tmp_path / "Makefile").touch()
    locks = []
    original = workspace_module.FileLock
    original_release = original.release

    def create(*args, **kwargs):
        lock = original(*args, **kwargs)
        locks.append(lock)
        return lock

    def release(lock, *args, **kwargs):
        interrupt = Path(lock.lock_file).name == "preview.lock" and lock.is_locked
        original_release(lock, *args, **kwargs)
        if interrupt:
            raise KeyboardInterrupt

    monkeypatch.setattr(workspace_module, "FileLock", create)
    monkeypatch.setattr(original, "release", release)
    result = invoke(tmp_path)
    assert result.exit_code == 130, result.output
    assert len(locks) == 2
    assert not any(lock.is_locked for lock in locks)


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
@pytest.mark.parametrize("mode", ["make", "quarto", "fallback"])
@pytest.mark.parametrize("ignore_interrupt", [False, True])
@pytest.mark.parametrize(
    "signum", [signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM)]
)
def test_cli_only_signal_stops_recipe_and_releases_ownership(
    tmp_path, mode, ignore_interrupt, signum
):
    if mode != "quarto" and shutil.which("make") is None:
        pytest.skip("requires GNU Make")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    server = tmp_path / "quarto"
    server.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\n"
        "import os, signal, socket, time\n"
        + (f"signal.signal({signum}, signal.SIG_IGN)\n" if ignore_interrupt else "")
        + "server = socket.socket()\n"
        + f"server.bind(('127.0.0.1', {port})); server.listen()\n"
        + "Path('serving').write_text(str(os.getpid()))\n"
        + "time.sleep(60)\n"
    )
    server.chmod(0o755)
    if mode == "make":
        (tmp_path / "Makefile").write_text(f"preview:\n\t@{server}\n")
    else:
        (tmp_path / "_quarto.yml").write_text("project: {}\n")
        if mode == "fallback":
            (tmp_path / "Makefile").write_text("check:\n")
    script = (
        "from asta.cli import cli\n"
        "from asta.commands import workspace\n"
        f"workspace.PREVIEW_PORT = {port}\n"
        "cli()\n"
    )
    env = dict(os.environ, PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    with (tmp_path / "launcher.log").open("w+") as log:
        launcher = subprocess.Popen(
            [sys.executable, "-c", script, "workspace", "preview"],
            cwd=tmp_path,
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        recipe_group = None
        try:
            deadline = time.monotonic() + 5
            while not (tmp_path / "serving").exists():
                assert launcher.poll() is None
                assert time.monotonic() < deadline
                time.sleep(0.01)
            recipe_group = os.getpgid(int((tmp_path / "serving").read_text()))
            assert recipe_group != os.getpgid(launcher.pid)
            launcher.send_signal(signum)
            assert launcher.wait(timeout=6) == 128 + signum
            assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()
            with FileLock(tmp_path / workspace_module.PREVIEW_LOCK, timeout=0):
                pass
            deadline = time.monotonic() + 2
            while True:
                try:
                    socket.create_connection(("127.0.0.1", port), 0.1).close()
                except OSError:
                    break
                assert time.monotonic() < deadline, "preview child kept serving"
                time.sleep(0.01)
            log.seek(0)
            output = log.read()
            assert "Aborted" not in output
            assert "failed (exit" not in output
        finally:
            for group in (recipe_group, launcher.pid):
                if group is not None:
                    try:
                        os.killpg(group, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            launcher.wait(timeout=5)


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
        "import os, socket, time\n"
        "Path('recipe-pid').write_text(str(os.getpid()))\n"
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
            if (tmp_path / "recipe-pid").exists():
                try:
                    os.killpg(
                        os.getpgid(int((tmp_path / "recipe-pid").read_text())),
                        signal.SIGKILL,
                    )
                except ProcessLookupError:
                    pass
        # A killed owner leaves JSON, but the kernel releases its ownership lock.
        assert (tmp_path / workspace_module.PREVIEW_STATE).exists()
        with FileLock(tmp_path / workspace_module.PREVIEW_LOCK, timeout=0):
            pass


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
@pytest.mark.parametrize("mode", ["make", "quarto", "fallback"])
def test_projects_cannot_share_a_preview_port_during_startup(tmp_path, mode):
    if mode != "quarto" and shutil.which("make") is None:
        pytest.skip("requires GNU Make")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    projects = [tmp_path / name for name in ("first", "second")]
    for project in projects:
        project.mkdir()
        server = project / "quarto"
        server.write_text(
            f"#!{sys.executable}\n"
            "from pathlib import Path\n"
            "import socket, time\n"
            "Path('starting').touch()\n"
            "while not Path('allow-listen').exists(): time.sleep(0.01)\n"
            "server = socket.socket()\n"
            + f"server.bind(('127.0.0.1', {port})); server.listen()\n"
            + "Path('listening').touch()\n"
            "time.sleep(60)\n"
        )
        server.chmod(0o755)
        if mode != "make":
            (project / "_quarto.yml").write_text("project: {}\n")
        if mode != "quarto":
            (project / "Makefile").write_text(
                f"preview:\n\t@{sys.executable} quarto\n"
                if mode == "make"
                else "other:\n"
            )
    script = (
        "from asta.cli import cli\n"
        "from asta.commands import workspace\n"
        f"workspace.PREVIEW_PORT = {port}\n"
        "workspace.PREVIEW_START_TIMEOUT = 0.2\n"
        "cli()\n"
    )

    def start(project):
        return subprocess.Popen(
            [sys.executable, "-c", script, "workspace", "preview"],
            cwd=project,
            env=dict(os.environ, PATH=f"{project}{os.pathsep}{os.environ['PATH']}"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )

    def await_file(project, name, process):
        deadline = time.monotonic() + 5
        while not (project / name).exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)

    processes = []
    try:
        owner = start(projects[0])
        processes.append(owner)
        await_file(projects[0], "starting", owner)
        contender = start(projects[1])
        processes.append(contender)
        output, _ = contender.communicate(timeout=5)
        assert contender.returncode == 1, output
        assert "another project" in output
        assert not (projects[1] / "starting").exists()
        assert not (projects[1] / workspace_module.PREVIEW_STATE).exists()

        (projects[0] / "allow-listen").touch()
        await_file(projects[0], "listening", owner)
        for project in projects:
            repeat = start(project)
            processes.append(repeat)
            output, _ = repeat.communicate(timeout=5)
            assert repeat.returncode == (0 if project == projects[0] else 1), output
            assert ("Preview already running" in output) == (project == projects[0])

        owner.send_signal(signal.SIGTERM)
        owner.communicate(timeout=5)
        assert owner.returncode == 143
        assert not (projects[0] / workspace_module.PREVIEW_STATE).exists()
        (projects[1] / "allow-listen").touch()
        replacement = start(projects[1])
        processes.append(replacement)
        await_file(projects[1], "listening", replacement)
        replacement.send_signal(signal.SIGTERM)
        replacement.communicate(timeout=5)
        assert replacement.returncode == 143
        assert not (projects[1] / workspace_module.PREVIEW_STATE).exists()
    finally:
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=5)


@pytest.mark.parametrize("empty", [False, True])
def test_phony_preview_with_real_directory_preserves_success(
    tmp_path, real_make, empty
):
    (tmp_path / "preview").mkdir()
    (tmp_path / "Makefile").write_text(
        ".PHONY: preview\npreview:\n" + ("" if empty else "\t@echo custom > calls\n")
    )
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    if not empty:
        assert (tmp_path / "calls").read_text() == "custom\n"
    assert real_make == []


@pytest.mark.parametrize("project_file", ["Makefile", "_quarto.yml"])
def test_state_write_failure_reports_ownership_and_releases_lock(
    tmp_path, ran, monkeypatch, project_file
):
    (tmp_path / project_file).touch()
    write_text = Path.write_text

    def fail_state(path, *args, **kwargs):
        if path == tmp_path / workspace_module.PREVIEW_STATE:
            raise FileNotFoundError("preview cache was removed")
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_state)
    result = invoke(tmp_path)
    assert result.exit_code == 1, result.output
    assert "Cannot record preview ownership" in result.output
    assert "not installed" not in result.output
    assert ran.calls == []
    with FileLock(tmp_path / workspace_module.PREVIEW_LOCK, timeout=0):
        pass


@pytest.mark.parametrize("failure", [False, True])
def test_preview_restores_signal_handlers(tmp_path, ran, failure):
    (tmp_path / "Makefile").touch()
    ran.returncode = 2 if failure else 0
    signals = [signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        signals.append(signal.SIGHUP)
    handlers = {signum: signal.getsignal(signum) for signum in signals}
    invoke(tmp_path)
    assert {signum: signal.getsignal(signum) for signum in signals} == handlers


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
@pytest.mark.parametrize("stage", ["construct", "start"])
@pytest.mark.parametrize("exception", [KeyboardInterrupt, RuntimeError])
def test_reader_setup_exception_cleans_spawned_child(
    tmp_path, real_make, monkeypatch, stage, exception
):
    (tmp_path / "Makefile").write_text("preview:\n\t@sleep 60\n")
    processes = []
    popen = subprocess.Popen

    def record(*args, **kwargs):
        child = popen(*args, **kwargs)
        processes.append(child)
        return child

    def interrupt(*args, **kwargs):
        raise exception("reader setup interrupted")

    monkeypatch.setattr(workspace_module.subprocess, "Popen", record)
    if stage == "construct":
        monkeypatch.setattr(workspace_module.threading, "Thread", interrupt)
    else:
        monkeypatch.setattr(workspace_module.threading.Thread, "start", interrupt)
    try:
        result = invoke(tmp_path)
        assert result.exit_code == (130 if exception is KeyboardInterrupt else 1)
        assert len(processes) == 1
        assert processes[0].poll() is not None
        assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()
        with FileLock(tmp_path / workspace_module.PREVIEW_LOCK, timeout=0):
            pass
    finally:
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
def test_same_project_reattach_before_ownership_record_waits_for_launcher(tmp_path):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    (tmp_path / "_quarto.yml").touch()
    server = tmp_path / "quarto"
    server.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\nimport socket, time\n"
        f"server = socket.socket(); server.bind(('127.0.0.1', {port})); server.listen()\n"
        "Path('listening').touch()\ntime.sleep(60)\n"
    )
    server.chmod(0o755)
    script = (
        "from pathlib import Path\nimport os, time\n"
        "from asta.cli import cli\nfrom asta.commands import workspace\n"
        f"workspace.PREVIEW_PORT = {port}\n"
        "original_acquire = workspace.FileLock.acquire\n"
        "def acquire(lock, *args, **kwargs):\n"
        " if os.environ.get('PR184_REATTACH') and Path(lock.lock_file).name == 'preview.lock':\n"
        "  Path('reattach-attempt').touch()\n"
        " result = original_acquire(lock, *args, **kwargs)\n"
        f" if Path(lock.lock_file).name == 'preview-{port}.lock':\n"
        "  Path('reserved').touch()\n"
        "  while not Path('allow-start').exists(): time.sleep(0.01)\n"
        " return result\n"
        "workspace.FileLock.acquire = acquire\ncli()\n"
    )
    processes = []
    env = dict(os.environ, PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    def start(*, reattach=False):
        process = subprocess.Popen(
            [sys.executable, "-c", script, "workspace", "preview"],
            cwd=tmp_path,
            env=dict(env, PR184_REATTACH="1" if reattach else ""),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        processes.append(process)
        return process

    try:
        owner = start()
        deadline = time.monotonic() + 5
        while not (tmp_path / "reserved").exists():
            assert owner.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()
        reattach = start(reattach=True)
        deadline = time.monotonic() + 5
        while not (tmp_path / "reattach-attempt").exists():
            assert reattach.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)
        with pytest.raises(subprocess.TimeoutExpired):
            reattach.communicate(timeout=0.3)
        (tmp_path / "allow-start").touch()
        output, _ = reattach.communicate(timeout=5)
        assert reattach.returncode == 0, output
        assert "Preview already running" in output
        owner.send_signal(signal.SIGTERM)
        owner.communicate(timeout=5)
        assert owner.returncode == 143
        assert not (tmp_path / workspace_module.PREVIEW_STATE).exists()
    finally:
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


@pytest.mark.parametrize(
    "signum", [signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM)]
)
def test_termination_during_reuse_preserves_owner(tmp_path, ran, monkeypatch, signum):
    (tmp_path / "Makefile").touch()
    write_state(tmp_path)
    state = (tmp_path / workspace_module.PREVIEW_STATE).read_bytes()

    def terminate(seconds):
        signal.getsignal(signum)(signum, None)

    monkeypatch.setattr(workspace_module.time, "sleep", terminate)
    with FileLock(tmp_path / workspace_module.PREVIEW_LOCK):
        result = invoke(tmp_path)
    assert result.exit_code == 128 + signum
    assert (tmp_path / workspace_module.PREVIEW_STATE).read_bytes() == state
    assert ran.calls == []


def test_slow_startup_reattach_waits_beyond_ten_seconds(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").touch()
    write_state(tmp_path)
    probes = iter([False, True])
    monkeypatch.setattr(workspace_module, "preview_running", lambda: next(probes))
    clock = iter([0, 20])
    monkeypatch.setattr(workspace_module, "monotonic", lambda: next(clock, 20))
    monkeypatch.setattr(workspace_module.time, "sleep", lambda _: None)
    with FileLock(tmp_path / workspace_module.PREVIEW_LOCK):
        result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "already running" in result.output
    assert ran.calls == []
