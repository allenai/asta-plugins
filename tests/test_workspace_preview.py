"""`asta workspace preview` delegates to the project's own preview."""

import shutil
import signal
import socket
import subprocess
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

    def __call__(self, command, cwd, check, **kwargs):
        self.calls.append((command, Path(cwd)))
        if command == ["make", "--question", "preview"]:
            assert kwargs["env"]["LC_ALL"] == "C"
            assert kwargs["timeout"] == workspace_module.MAKE_PROBE_TIMEOUT
            return type(
                "Result",
                (),
                {
                    "returncode": 1 if self.make_preview else 2,
                    "stderr": "" if self.make_preview else self.make_error,
                },
            )()
        return type("Result", (), {"returncode": self.returncode})()


@pytest.fixture
def ran(monkeypatch):
    runner = Ran()
    monkeypatch.setattr(workspace_module.subprocess, "run", runner)
    monkeypatch.setattr(workspace_module, "preview_running", lambda: False)
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
    assert "Quarto preview: http://localhost:4848/" in result.output
    assert ran.calls == [
        (["make", "--question", "preview"], tmp_path.resolve()),
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
    assert "Quarto preview:" not in result.output
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
    assert "Quarto preview:" not in result.output
    assert ran.calls == []


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
        (["make", "--question", "preview"], tmp_path.resolve()),
        (["quarto", "preview", "--no-browser", "--port", "4848"], tmp_path.resolve()),
    ]


def test_missing_make_falls_back_to_quarto(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("check:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")

    def run(command, **kwargs):
        if command[0] == "make":
            raise FileNotFoundError("make")
        return ran(command, **kwargs)

    monkeypatch.setattr(workspace_module.subprocess, "run", run)
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert ran.calls == [
        (["quarto", "preview", "--no-browser", "--port", "4848"], tmp_path.resolve())
    ]


def test_make_probe_timeout_still_uses_project_preview(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("include rules.mk\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")

    def run(command, **kwargs):
        if "--question" in command:
            assert kwargs["timeout"] == workspace_module.MAKE_PROBE_TIMEOUT
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return ran(command, **kwargs)

    monkeypatch.setattr(workspace_module.subprocess, "run", run)
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert ran.calls == [(["make", "preview"], tmp_path.resolve())]


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
    assert result.exit_code == 0, result.output
    assert "failed" not in result.output


def test_keyboard_interrupt_exits_cleanly(tmp_path, ran, monkeypatch):
    (tmp_path / "_quarto.yml").write_text("project: {}\n")

    def run(command, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(workspace_module.subprocess, "run", run)
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
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
    assert "Quarto preview:" not in result.output
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
