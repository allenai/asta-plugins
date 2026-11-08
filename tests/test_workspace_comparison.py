"""The CLI owns both built-site comparisons and optional browser provisioning."""

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


def test_partial_selection_needs_no_external_probes(tmp_path, monkeypatch):
    before = tmp_path / "before"
    after = tmp_path / "after"
    for root in (before, after):
        root.mkdir()
        (root / "index.qmd").write_text("a page")

    def git(root, *args):
        stdout = "index.qmd\0" if args[0] == "diff" else ""
        return subprocess.CompletedProcess(args, 0, stdout=stdout)

    monkeypatch.setattr(module, "_git", git)
    monkeypatch.setattr(module, "_ls_files", lambda *args: [])
    assert module._changed_comparison_pages(after, before, "main") == ["index.qmd"]


def test_after_inspect_normalizes_render_inputs(tmp_path, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 0, stdout='{"files":{"input":["page.qmd"]}}'
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert module._comparison_inputs(tmp_path) == {(tmp_path / "page.qmd").resolve()}
    assert calls == [["quarto", "inspect", str(tmp_path)]]


def test_failed_after_inspect_does_not_hide_pages(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("no quarto")

    monkeypatch.setattr(subprocess, "run", fail)
    assert module._comparison_inputs(tmp_path) is None


def test_unrelated_page_edit_skips_paper_build_and_tool_checks(tmp_path, monkeypatch):
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Paper\end{document}"
    )
    site = tmp_path / "_site"
    site.mkdir()

    def git(project, *args):
        return subprocess.CompletedProcess(
            args, 0, stdout="page.qmd\0" if args[0] == "diff" else ""
        )

    def discovery(command, **kwargs):
        assert command[1].endswith("paper-discovery.py")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"papers":["paper"],"removed":[],"main_files":{"paper":"main.tex"}}',
        )

    def unexpected(*args):
        pytest.fail("unrelated edit must not check TeX or snapshot/build the paper")

    monkeypatch.setattr(module, "_git", git)
    monkeypatch.setattr(module, "_ls_files", lambda *args: [])
    monkeypatch.setattr(subprocess, "run", discovery)
    monkeypatch.setattr(module.shutil, "which", unexpected)
    monkeypatch.setattr(module, "_commit_working_tree", unexpected)
    module._paper_previews(tmp_path, "base", site)
    assert not (site / "paper-previews").exists()
