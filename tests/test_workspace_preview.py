"""`asta workspace preview` delegates to the project's own preview."""

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

from asta.cli import cli
from asta.commands import workspace as workspace_module
from asta.commands.workspace import preview_running


class Ran:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.make_preview = True
        self.make_error = "make: *** No rule to make target 'preview'.  Stop.\n"
        self.calls: list[tuple[list[str], Path]] = []

    def popen(self, command, cwd, **kwargs):
        self.calls.append((command, Path(cwd)))
        assert command == ["make", "--question", "--print-data-base", "preview"]
        assert kwargs["env"]["LC_ALL"] == "C"
        assert (
            not {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "GNUMAKEFLAGS", "MAKEFILES"}
            & kwargs["env"].keys()
        )
        assert kwargs["start_new_session"] == (os.name == "posix")
        kwargs["stdout"].write(
            "\n# Make data base, printed on test\n# Files\n\npreview:\n"
            if self.make_preview
            else ""
        )
        kwargs["stderr"].write("" if self.make_preview else self.make_error)

        def wait(timeout):
            assert timeout == workspace_module.MAKE_PROBE_TIMEOUT
            return 1 if self.make_preview else 2

        return type("Process", (), {"wait": staticmethod(wait)})()

    def __call__(self, command, cwd, check, **kwargs):
        self.calls.append((command, Path(cwd)))
        return type("Result", (), {"returncode": self.returncode})()


@pytest.fixture
def ran(monkeypatch):
    runner = Ran()
    monkeypatch.setattr(workspace_module.subprocess, "run", runner)
    monkeypatch.setattr(workspace_module.subprocess, "Popen", runner.popen)
    monkeypatch.setattr(workspace_module, "preview_running", lambda: False)
    monkeypatch.setattr(workspace_module.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.delenv("CODESPACE_NAME", raising=False)
    return runner


def invoke(project: Path):
    return CliRunner().invoke(cli, ["workspace", "preview", "--project", str(project)])


@pytest.mark.parametrize("makefile_name", ["GNUmakefile", "makefile", "Makefile"])
def test_makefile_target_wins(tmp_path, ran, makefile_name):
    (tmp_path / makefile_name).write_text("preview:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "Preview: http://localhost:4848/" in result.output
    assert ran.calls == [
        (["make", "--question", "--print-data-base", "preview"], tmp_path.resolve()),
        (["make", "preview"], tmp_path.resolve()),
    ]


def test_quarto_only_project(tmp_path, ran):
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    assert invoke(tmp_path).exit_code == 0
    assert ran.calls == [
        (["quarto", "preview", "--no-browser", "--port", "4848"], tmp_path.resolve())
    ]


def test_occupied_port_does_not_claim_a_preview(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    monkeypatch.setattr(workspace_module, "preview_running", lambda: True)
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "Port 4848 is already in use" in result.output
    assert "cannot verify" in result.output
    assert "Preview:" not in result.output
    assert ran.calls == []


def test_preview_probe_needs_only_a_listening_socket(monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        monkeypatch.setattr(workspace_module, "PREVIEW_PORT", listener.getsockname()[1])
        listener.listen()
        assert workspace_module.preview_running()
    assert not workspace_module.preview_running()


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_unrelated_real_listener_is_rejected(tmp_path, ran, monkeypatch, host):
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    monkeypatch.setattr(workspace_module, "preview_running", preview_running)
    family = socket.AF_INET6 if host == "::1" else socket.AF_INET
    with socket.socket(family) as listener:
        if host == "::1":
            listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        try:
            listener.bind((host, 0))
        except OSError:
            if host == "::1":
                pytest.skip("IPv6 loopback unavailable")
            raise
        monkeypatch.setattr(workspace_module, "PREVIEW_PORT", listener.getsockname()[1])
        listener.listen()
        result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "already in use" in result.output
    assert "cannot verify" in result.output
    assert "Preview:" not in result.output
    assert ran.calls == []


def test_attach_skips_occupied_port_without_claiming_server(tmp_path, ran, monkeypatch):
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    monkeypatch.setattr(workspace_module, "preview_running", lambda: True)
    result = CliRunner().invoke(
        cli, ["workspace", "preview", "--project", str(tmp_path), "--if-needed"]
    )
    assert result.exit_code == 0, result.output
    assert "skipping preview startup" in result.output
    assert "may belong to another project" in result.output
    assert "Preview:" not in result.output
    assert ran.calls == []


def test_attach_starts_project_preview_when_port_is_free(tmp_path, ran):
    (tmp_path / "Makefile").write_text("preview:\n")
    result = CliRunner().invoke(
        cli, ["workspace", "preview", "--project", str(tmp_path), "--if-needed"]
    )
    assert result.exit_code == 0, result.output
    assert ran.calls[-1] == (["make", "preview"], tmp_path.resolve())


def test_empty_project_does_not_require_a_free_port(tmp_path, ran, monkeypatch):
    monkeypatch.setattr(workspace_module, "preview_running", lambda: True)
    result = invoke(tmp_path)
    assert result.exit_code == 0
    assert "nothing to preview" in result.output


@pytest.mark.parametrize("quote", ["'", "`"])
def test_makefile_without_preview_falls_back_to_quarto(tmp_path, ran, quote):
    (tmp_path / "Makefile").write_text("check:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    ran.make_preview = False
    ran.make_error = f"make: *** No rule to make target {quote}preview'.  Stop.\n"
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert ran.calls == [
        (["make", "--question", "--print-data-base", "preview"], tmp_path.resolve()),
        (["quarto", "preview", "--no-browser", "--port", "4848"], tmp_path.resolve()),
    ]


def test_missing_make_falls_back_to_quarto(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("check:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")

    def popen(command, **kwargs):
        raise FileNotFoundError("make")

    monkeypatch.setattr(workspace_module.subprocess, "Popen", popen)
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert ran.calls == [
        (["quarto", "preview", "--no-browser", "--port", "4848"], tmp_path.resolve())
    ]


@pytest.mark.skipif(shutil.which("make") is None, reason="requires GNU Make")
@pytest.mark.parametrize("flags", ["-n", "-k", "-i", "--eval=preview:"])
@pytest.mark.parametrize("variable", ["MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS"])
def test_make_probe_ignores_caller_flags(tmp_path, monkeypatch, flags, variable):
    (tmp_path / "Makefile").write_text("check:\n")
    monkeypatch.setenv(variable, flags)
    monkeypatch.setenv("MAKELEVEL", "1")
    assert not workspace_module.make_has_preview(tmp_path)


@pytest.mark.skipif(shutil.which("make") is None, reason="requires GNU Make")
def test_make_probe_ignores_caller_makefiles(tmp_path, monkeypatch):
    (tmp_path / "Makefile").write_text("check:\n")
    extra_rules = tmp_path / "extra.mk"
    extra_rules.write_text("preview:\n")
    monkeypatch.setenv("MAKEFILES", str(extra_rules))
    assert not workspace_module.make_has_preview(tmp_path)


@pytest.mark.skipif(shutil.which("make") is None, reason="requires GNU Make")
@pytest.mark.parametrize(
    "variable", ["MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "MAKEFILES"]
)
def test_real_preview_ignores_caller_make_controls(tmp_path, monkeypatch, variable):
    (tmp_path / "Makefile").write_text("preview:\n\t@echo $(CUSTOM_VALUE) > started\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    extra_rules = tmp_path / "extra.mk"
    extra_rules.write_text("preview:\n\t@echo injected > started\n")
    monkeypatch.setenv(variable, str(extra_rules) if variable == "MAKEFILES" else "-n")
    monkeypatch.setenv("CUSTOM_VALUE", "project-setting")
    monkeypatch.setattr(workspace_module, "preview_running", lambda: False)
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert (tmp_path / "started").read_text() == "project-setting\n"


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
def test_make_probe_timeout_with_descendants_holding_output(tmp_path):
    fake_make = tmp_path / "make"
    fake_make.write_text(
        f"#!{sys.executable}\n"
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "time.sleep(60)\n"
    )
    fake_make.chmod(0o755)
    script = (
        "from pathlib import Path\n"
        "from asta.commands import workspace\n"
        "workspace.MAKE_PROBE_TIMEOUT = 0.3\n"
        "assert workspace.make_has_preview(Path('.'))\n"
    )
    env = {**os.environ, "PATH": str(tmp_path)}
    # Isolate the old hanging implementation and clean up its descendants too.
    with (tmp_path / "probe.log").open("w+") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=tmp_path,
            env=env,
            stdout=output,
            stderr=output,
            start_new_session=True,
        )
        try:
            started = time.monotonic()
            process.wait(timeout=4)
            output.seek(0)
            assert process.returncode == 0, output.read()
            assert time.monotonic() - started < 3
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def test_make_probe_timeout_still_uses_project_preview(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("include rules.mk\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")

    class Probe:
        pid = 12345

        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("make", timeout)
            return -signal.SIGKILL

        def kill(self):
            pass

    monkeypatch.setattr(workspace_module.subprocess, "Popen", lambda *a, **kw: Probe())
    if os.name == "posix":
        monkeypatch.setattr(workspace_module.os, "killpg", lambda *a: None)
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert ran.calls == [(["make", "preview"], tmp_path.resolve())]
    assert "target detection timed out" in result.output


@pytest.mark.skipif(shutil.which("make") is None, reason="requires GNU Make")
@pytest.mark.parametrize("target", ["preview", "check"])
@pytest.mark.parametrize("makefile_name", ["GNUmakefile", "makefile", "Makefile"])
def test_real_make_included_rules_choose_the_preview(
    tmp_path, monkeypatch, target, makefile_name
):
    (tmp_path / makefile_name).write_text("include rules.mk\n")
    (tmp_path / "rules.mk").write_text(f"{target}:\n\t@echo ran >> calls\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    actual_run = subprocess.run
    quarto_calls = []

    def run(command, **kwargs):
        if command[0] == "quarto":
            quarto_calls.append((command, kwargs["cwd"]))
            return subprocess.CompletedProcess(command, 0)
        return actual_run(command, **kwargs)

    monkeypatch.setattr(workspace_module.subprocess, "run", run)
    monkeypatch.setattr(workspace_module, "preview_running", lambda: False)
    actual_which = shutil.which
    monkeypatch.setattr(
        workspace_module.shutil,
        "which",
        lambda name: "/bin/quarto" if name == "quarto" else actual_which(name),
    )
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    if target == "preview":
        assert (tmp_path / "calls").read_text() == "ran\n"
        assert quarto_calls == []
    else:
        assert not (tmp_path / "calls").exists()
        assert quarto_calls == [
            (
                ["quarto", "preview", "--no-browser", "--port", "4848"],
                tmp_path.resolve(),
            )
        ]


@pytest.mark.skipif(shutil.which("make") is None, reason="requires GNU Make")
def test_real_make_probe_can_fetch_included_rules(tmp_path):
    (tmp_path / "Makefile").write_text(
        "include rules.mk\nrules.mk:\n\t@printf 'preview:\\n' > rules.mk\n"
    )
    assert workspace_module.make_has_preview(tmp_path)
    assert (tmp_path / "rules.mk").read_text() == "preview:\n"


@pytest.mark.skipif(shutil.which("make") is None, reason="requires GNU Make")
@pytest.mark.parametrize("artifact", ["file", "directory"])
def test_preview_artifact_without_rule_falls_back_to_quarto(
    tmp_path, monkeypatch, artifact
):
    (tmp_path / "Makefile").write_text("check:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    if artifact == "file":
        (tmp_path / "preview").touch()
    else:
        (tmp_path / "preview").mkdir()
    actual_run = subprocess.run
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "quarto":
            return subprocess.CompletedProcess(command, 0)
        return actual_run(command, **kwargs)

    monkeypatch.setattr(workspace_module.subprocess, "run", run)
    monkeypatch.setattr(workspace_module, "preview_running", lambda: False)
    monkeypatch.setattr(workspace_module.shutil, "which", lambda name: f"/bin/{name}")
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert calls[-1] == ["quarto", "preview", "--no-browser", "--port", "4848"]
    assert ["make", "preview"] not in calls


@pytest.mark.skipif(shutil.which("make") is None, reason="requires GNU Make")
def test_make_recipe_output_cannot_invent_a_preview_rule(tmp_path):
    (tmp_path / "Makefile").write_text(
        "define noise\nignored\n# Files\n\npreview:\n\nendef\n"
        "$(info $(noise))\ncheck:\n"
    )
    (tmp_path / "preview").touch()
    assert not workspace_module.make_has_preview(tmp_path)


@pytest.mark.skipif(shutil.which("make") is None, reason="requires GNU Make")
@pytest.mark.parametrize(
    "rules",
    [
        "preview:\n",
        ".PHONY: preview\n",
        "preview::\n\t@echo preview\n",
        "pre%:\n\t@echo preview\n",
        ".DEFAULT:\n\t@echo preview\n",
        "preview: dependency\ndependency:\n",
    ],
)
def test_real_preview_rules_win_even_with_existing_artifact(tmp_path, rules):
    (tmp_path / "Makefile").write_text(rules)
    (tmp_path / "preview").mkdir()
    assert workspace_module.make_has_preview(tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
@pytest.mark.skipif(shutil.which("make") is None, reason="requires GNU Make")
def test_make_probe_timeout_stops_include_remake_children(tmp_path):
    child = tmp_path / "child.py"
    child.write_text(
        "from pathlib import Path\n"
        "import os, time\n"
        "Path('child-started').write_text(str(os.getpgrp()))\n"
        "time.sleep(1)\n"
        "Path('child-survived').touch()\n"
        "time.sleep(60)\n"
    )
    (tmp_path / "Makefile").write_text(
        f"include rules.mk\nrules.mk:\n\t@{sys.executable} child.py & wait\n"
    )
    script = (
        "from pathlib import Path\n"
        "from asta.commands import workspace\n"
        "workspace.MAKE_PROBE_TIMEOUT = 0.5\n"
        "assert workspace.make_has_preview(Path('.'))\n"
    )
    with (tmp_path / "probe.log").open("w+") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=tmp_path,
            stdout=output,
            stderr=output,
            start_new_session=True,
        )
        try:
            process.wait(timeout=5)
            output.seek(0)
            assert process.returncode == 0, output.read()
            assert (tmp_path / "child-started").exists()
            time.sleep(1.5)
            assert not (tmp_path / "child-survived").exists()
        finally:
            marker = tmp_path / "child-started"
            if marker.exists():
                try:
                    os.killpg(int(marker.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


@pytest.mark.skipif(shutil.which("make") is None, reason="requires GNU Make")
@pytest.mark.parametrize(
    "makefile", ["preview: missing-input\n", "not valid make syntax\n"]
)
def test_real_make_errors_do_not_fall_back(tmp_path, monkeypatch, makefile):
    monkeypatch.setattr(workspace_module, "preview_running", lambda: False)
    (tmp_path / "Makefile").write_text(makefile)
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "make preview failed (exit 2)" in result.output
    assert "quarto is not installed" not in result.output


def test_codespaces_url(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    monkeypatch.setenv("CODESPACE_NAME", "demo")
    monkeypatch.delenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", raising=False)
    assert "https://demo-4848.app.github.dev/" in invoke(tmp_path).output


@pytest.mark.parametrize(
    ("project_file", "command"),
    [
        ("Makefile", "make preview"),
        ("_quarto.yml", "quarto preview --no-browser --port 4848"),
    ],
)
def test_failure_is_reported(tmp_path, ran, project_file, command):
    (tmp_path / project_file).touch()
    ran.returncode = 2
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert f"{command} failed (exit 2)" in result.output


@pytest.mark.parametrize("returncode", [-signal.SIGINT, 130])
def test_interrupted_preview_exits_cleanly(tmp_path, ran, returncode):
    (tmp_path / "Makefile").write_text("preview:\n")
    ran.returncode = returncode
    result = invoke(tmp_path)
    assert result.exit_code == 130, result.output
    assert "failed" not in result.output


def test_keyboard_interrupt_exits_cleanly(tmp_path, ran, monkeypatch):
    (tmp_path / "_quarto.yml").write_text("project: {}\n")

    def run(command, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(workspace_module.subprocess, "run", run)
    result = invoke(tmp_path)
    assert result.exit_code == 130, result.output
    assert "Aborted" not in result.output


def test_nothing_to_preview(tmp_path, ran):
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "nothing to preview" in result.output
    assert ran.calls == []


def test_nonexistent_project_is_rejected(tmp_path, ran):
    project = tmp_path / "missing-project"
    result = invoke(project)
    assert result.exit_code != 0
    assert "does not exist" in result.output
    assert str(project) in result.output
    assert "nothing to preview" not in result.output
    assert "Preview:" not in result.output
    assert ran.calls == []


@pytest.mark.parametrize(
    ("project_file", "executable"), [("Makefile", "make"), ("_quarto.yml", "quarto")]
)
def test_missing_preview_tool_is_reported(
    tmp_path, ran, monkeypatch, project_file, executable
):
    (tmp_path / project_file).touch()

    def missing_tool(command, cwd, check, **kwargs):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(workspace_module.subprocess, "run", missing_tool)
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert f"{executable} is not installed" in result.output


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
