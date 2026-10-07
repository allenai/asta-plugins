"""`asta workspace preview` delegates to the project's own preview."""

import shutil
import socket
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from asta.cli import cli
from asta.commands import workspace as workspace_module


class Ran:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.make_preview = True
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command, cwd, check, **kwargs):
        self.calls.append((command, Path(cwd)))
        if command == ["make", "--question", "preview"]:
            assert kwargs["env"]["LC_ALL"] == "C"
            return type(
                "Result",
                (),
                {
                    "returncode": 1 if self.make_preview else 2,
                    "stderr": ""
                    if self.make_preview
                    else "make: *** No rule to make target 'preview'.  Stop.\n",
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


def test_makefile_target_wins(tmp_path, ran):
    (tmp_path / "Makefile").write_text("preview:\n")
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
    assert ran.calls == []


def test_preview_probe_needs_only_a_listening_socket(monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        monkeypatch.setattr(workspace_module, "PREVIEW_PORT", listener.getsockname()[1])
        listener.listen()
        assert workspace_module.preview_running()
    assert not workspace_module.preview_running()


def test_unrelated_real_listener_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        monkeypatch.setattr(workspace_module, "PREVIEW_PORT", listener.getsockname()[1])
        listener.listen()
        result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "already in use" in result.output
    assert "cannot verify" in result.output


def test_empty_project_does_not_require_a_free_port(tmp_path, ran, monkeypatch):
    monkeypatch.setattr(workspace_module, "preview_running", lambda: True)
    result = invoke(tmp_path)
    assert result.exit_code == 0
    assert "nothing to preview" in result.output


def test_makefile_without_preview_falls_back_to_quarto(tmp_path, ran):
    (tmp_path / "Makefile").write_text("check:\n")
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    ran.make_preview = False
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert ran.calls == [
        (["make", "--question", "preview"], tmp_path.resolve()),
        (["quarto", "preview", "--no-browser", "--port", "4848"], tmp_path.resolve()),
    ]


@pytest.mark.skipif(shutil.which("make") is None, reason="requires GNU Make")
@pytest.mark.parametrize("target", ["preview", "check"])
def test_real_make_included_rules_choose_the_preview(tmp_path, monkeypatch, target):
    (tmp_path / "Makefile").write_text("include rules.mk\n")
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
@pytest.mark.parametrize(
    "makefile", ["preview: missing-input\n", "not valid make syntax\n"]
)
def test_real_make_errors_do_not_fall_back(tmp_path, monkeypatch, makefile):
    monkeypatch.setattr(workspace_module, "preview_running", lambda: False)
    (tmp_path / "Makefile").write_text(makefile)
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "Quarto preview failed" in result.output
    assert "quarto is not installed" not in result.output


def test_codespaces_url(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    monkeypatch.setenv("CODESPACE_NAME", "demo")
    monkeypatch.delenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", raising=False)
    assert "https://demo-4848.app.github.dev/" in invoke(tmp_path).output


def test_failure_is_reported(tmp_path, ran):
    (tmp_path / "Makefile").write_text("preview:\n")
    ran.returncode = 2
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert "Quarto preview failed" in result.output


def test_nothing_to_preview(tmp_path, ran):
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "nothing to preview" in result.output
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
