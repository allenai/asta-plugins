"""The CLI owns both built-site comparisons and optional browser provisioning."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from asta.commands import workspace as module


def site(path, text):
    path.mkdir()
    (path / "index.html").write_text(
        f"<html><head><title>Site</title></head><body><main><p>{text}</p></main></body></html>"
    )
    return path


def test_prebuilt_sites_use_installed_comparator(tmp_path):
    before = site(tmp_path / "before", "old finding")
    after = site(tmp_path / "after", "new finding")
    result = CliRunner().invoke(
        module.workspace,
        ["what-changed", "--before-site", str(before), "--after-site", str(after)],
    )
    assert result.exit_code == 0, result.output
    assert "<ins" in (after / "what-changed.html").read_text()
    assert "old finding" in (before / "index.html").read_text()


def test_failed_comparison_preserves_previous_site(tmp_path, monkeypatch):
    before = site(tmp_path / "before", "old finding")
    after = site(tmp_path / "after", "new finding")
    (after / "what-changed.html").write_text("previous report")
    script = tmp_path / "fail.py"
    script.write_text("raise SystemExit(4)")
    monkeypatch.setattr(module, "_comparison_script", lambda: script)
    result = CliRunner().invoke(
        module.workspace,
        ["what-changed", "--before-site", str(before), "--after-site", str(after)],
    )
    assert result.exit_code != 0
    assert (after / "what-changed.html").read_text() == "previous report"
    assert "new finding" in (after / "index.html").read_text()


def test_prose_never_provisions_browser(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("prose must not run uv")

    monkeypatch.setattr(subprocess, "run", unexpected)
    command, _ = module._comparison_python(False)
    assert command == [sys.executable]


def test_deck_browser_is_pinned_and_cached(tmp_path, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=str(tmp_path))

    monkeypatch.setattr(subprocess, "run", run)
    command, env = module._comparison_python(True)
    assert "playwright==1.64.1" in command
    assert calls[1][0][-4:] == ["-m", "playwright", "install", "chromium"]
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "asta-chromium")


def test_relative_uv_cache_is_resolved_once_and_browser_shared(tmp_path, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UV_CACHE_DIR", ".uv-cache")
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(subprocess, "run", run)
    _, env = module._comparison_python(True)
    assert env["UV_CACHE_DIR"] == str(tmp_path / ".uv-cache")
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(
        Path(tempfile.gettempdir()) / "asta-chromium"
    )
    assert all(
        kwargs["env"]["UV_CACHE_DIR"] == env["UV_CACHE_DIR"] for _, kwargs in calls
    )


def test_unavailable_browser_dependencies_fall_back(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise OSError("cache unavailable")

    monkeypatch.setattr(subprocess, "run", fail)
    command, _ = module._comparison_python(True)
    assert command == [sys.executable]
    assert "run outside it to see rendered slides" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        ["main", "--before-site", ".", "--after-site", "."],
        ["--before-site", "."],
        ["--after-site", "."],
    ],
)
def test_ambiguous_inputs_fail(arguments):
    result = CliRunner().invoke(module.workspace, ["what-changed", *arguments])
    assert result.exit_code != 0


def test_partial_selection_checks_both_projects_and_guards_recursive_probes(
    tmp_path, monkeypatch
):
    before = tmp_path / "before"
    after = tmp_path / "after"
    for root in (before, after):
        root.mkdir()
        (root / "index.qmd").write_text("a page")

    def git(root, *args):
        stdout = "index.qmd\0" if args[0] == "diff" else ""
        return subprocess.CompletedProcess(args, 0, stdout=stdout)

    seen = []

    def run(command, **kwargs):
        seen.append(command[0])
        if command[0] == "quarto":
            return subprocess.CompletedProcess(
                command, 0, stdout='{"files":{"input":["index.qmd"]}}'
            )
        shim = Path(kwargs["env"]["PATH"].split(os.pathsep)[0]) / "quarto"
        assert shim.read_text() == "#!/bin/sh\nexit 0\n"
        return subprocess.CompletedProcess(
            command, 0, stdout=": asta-workspace-render-page-selection-v1;"
        )

    monkeypatch.setattr(module, "_git", git)
    monkeypatch.setattr(subprocess, "run", run)
    assert module._changed_comparison_pages(after, before, "main") == ["index.qmd"]
    assert seen == ["quarto", "make", "quarto", "make"]
