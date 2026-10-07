"""`asta workspace preview` delegates to the project's own preview."""

import socket
from pathlib import Path

import pytest
from click.testing import CliRunner

from asta.cli import cli
from asta.commands import workspace as workspace_module


class Ran:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command, cwd, check):
        self.calls.append((command, Path(cwd)))
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
    assert ran.calls == [(["make", "preview"], tmp_path.resolve())]


def test_quarto_only_project(tmp_path, ran):
    (tmp_path / "_quarto.yml").write_text("project: {}\n")
    assert invoke(tmp_path).exit_code == 0
    assert ran.calls == [
        (["quarto", "preview", "--no-browser", "--port", "4848"], tmp_path.resolve())
    ]


def test_reuses_running_preview(tmp_path, ran, monkeypatch):
    (tmp_path / "Makefile").write_text("preview:\n")
    monkeypatch.setattr(workspace_module, "preview_running", lambda: True)
    result = invoke(tmp_path)
    assert result.exit_code == 0
    assert "reusing it" in result.output
    assert ran.calls == []


def test_preview_probe_needs_only_a_listening_socket(monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        monkeypatch.setattr(workspace_module, "PREVIEW_PORT", listener.getsockname()[1])
        listener.listen()
        assert workspace_module.preview_running()
    assert not workspace_module.preview_running()


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

    def missing_tool(command, cwd, check):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(workspace_module.subprocess, "run", missing_tool)
    result = invoke(tmp_path)
    assert result.exit_code != 0
    assert f"{executable} is not installed" in result.output
