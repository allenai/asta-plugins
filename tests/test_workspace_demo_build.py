"""The public demo is built in isolation from the single checked-in patch."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("patch_fails", [False, True])
def test_demo_build_is_fresh_and_patch_failure_is_fatal(
    tmp_path, monkeypatch, patch_fails
):
    spec = importlib.util.spec_from_file_location(
        "demo", ROOT / "scripts/build-workspace-demo.py"
    )
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    source = tmp_path / "source"
    (source / "scripts").mkdir(parents=True)
    (source / "examples").mkdir()
    (source / "examples/workspace-demo.patch").write_text("sample edit")
    demo.__file__ = str(source / "scripts/build-workspace-demo.py")
    monkeypatch.setattr(demo.subprocess, "check_output", lambda *a, **k: "abc123\n")
    calls = []
    clones = []

    def run(args, *, cwd, env, check):
        assert check
        assert env["ASTA_WORKSPACE_RESOLVED_SHA"] == "abc123"
        calls.append(args)
        if args[:2] == ("git", "clone"):
            clone = Path(args[-1])
            (clone / "examples/workspace").mkdir(parents=True)
            clones.append(clone)
        if args[:2] == ("git", "apply") and patch_fails:
            raise subprocess.CalledProcessError(1, args)
        if args[0] == "asta":
            report = cwd / ".asta/cache/what-changed"
            report.mkdir(parents=True)
            (report / "what-changed.html").write_text("built report")

    monkeypatch.setattr(demo.subprocess, "run", run)
    output = tmp_path / "published/demo"
    if patch_fails:
        with pytest.raises(subprocess.CalledProcessError):
            demo.build_demo(output)
        assert not output.exists()
        assert not any(c[0] == "asta" for c in calls)
    else:
        demo.build_demo(output)
        assert (output / "what-changed.html").read_text() == "built report"
        assert ("make", "workspace-assets", "workspace-viewers") in calls
        assert ("asta", "workspace", "what-changed", "--timings", "HEAD") in calls
    assert clones and not clones[0].exists()
    assert not (source / "examples/workspace").exists()


@pytest.mark.parametrize("prebuilt", [False, True])
def test_demo_acceptance_cli_accepts_explicit_site_path(
    tmp_path, monkeypatch, prebuilt
):
    monkeypatch.syspath_prepend(str(ROOT / "tests/browser"))
    spec = importlib.util.spec_from_file_location(
        "demo_check", ROOT / "tests/browser/local-what-changed-demo.py"
    )
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    project, artifacts = tmp_path / "project", tmp_path / "artifacts"
    args = (
        ["check", "--site", str(project), str(artifacts)]
        if prebuilt
        else ["check", str(project), str(artifacts)]
    )
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setattr(
        check.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stderr="", stdout=""),
    )
    calls = []
    monkeypatch.setattr(check, "check_site", lambda *args: calls.append(args))
    check.main()
    expected = project if prebuilt else project / ".asta/cache/what-changed"
    assert calls == [(expected, artifacts)]
