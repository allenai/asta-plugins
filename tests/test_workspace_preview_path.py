"""Independent preview builds use isolated committed sides, never local reports."""

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def test_preview_build_renders_both_sides_and_does_not_mutate_source(
    tmp_path, monkeypatch
):
    monkeypatch.syspath_prepend(str(ROOT / "tests/browser"))
    spec = importlib.util.spec_from_file_location(
        "preview_check", ROOT / "tests/browser/workspace-preview-path.py"
    )
    preview = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preview)
    source = tmp_path / "source"
    project = source / "examples/workspace"
    project.mkdir(parents=True)
    page = project / "index.qmd"
    page.write_text("Before\n")

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=source, text=True)

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@localhost")
    git("add", "examples/workspace/index.qmd")
    git("commit", "-qm", "Base")
    page.write_text("After\n")
    patch = git("diff")
    page.write_text("Before\n")
    (source / "examples/workspace-demo.patch").write_text(patch)
    git("add", "examples/workspace-demo.patch")
    git("commit", "-qm", "Demo patch")
    monkeypatch.setattr(preview, "ROOT", source)
    monkeypatch.setattr(preview, "report_signature", lambda site: (set(), [], {}))
    original_run = subprocess.run
    builds = []
    calls = []

    def run(args, **kwargs):
        cwd = Path(kwargs["cwd"])
        calls.append(args)
        if args[0] == "make":
            builds.append((cwd, (cwd / "index.qmd").read_text()))
            (cwd / "_site").mkdir()
        elif args[0] == "asta":
            assert "--before-site" in args and "--after-site" in args
            (cwd / "_site/what-changed.html").write_text("independent report")
        elif str(args[0]).endswith("python") or "paper-discovery.py" in str(args):
            return SimpleNamespace(stdout='{"papers": []}', returncode=0)
        else:
            return original_run(args, **kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(preview.subprocess, "run", run)
    checks = []
    fake_spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None))
    monkeypatch.setattr(
        preview.importlib.util, "spec_from_file_location", lambda *a: fake_spec
    )
    monkeypatch.setattr(
        preview.importlib.util,
        "module_from_spec",
        lambda spec: SimpleNamespace(
            check_site=lambda site, artifacts: checks.append(site)
        ),
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    preview.check_preview(artifacts)
    assert sorted(text for _, text in builds) == ["After\n", "Before\n"]
    assert checks and (artifacts / "preview-path-site/what-changed.html").is_file()
    assert all(not path.exists() for path, _ in builds)
    assert page.read_text() == "Before\n"
    assert git("status", "--porcelain") == ""
    assert not any(
        args[:3] == ("asta", "workspace", "what-changed")
        and "--before-site" not in args
        for args in calls
    )


def test_report_signature_includes_page_and_live_slide_marks(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/browser"))
    from report_signature import report_signature

    (tmp_path / "what-changed.html").write_text(
        '<section class="page-diff changed" id="prose"><ins>new <em>words</em></ins><del>old</del></section>'
    )
    deck = tmp_path / "what-changed-decks/after/slides.marked.html"
    deck.parent.mkdir(parents=True)
    deck.write_text(
        '<section id="slide"><p><del>removed</del> <ins>added</ins></p></section>'
    )
    pages, marks, decks = report_signature(tmp_path)
    assert pages == {"prose"}
    assert marks == [("prose", "ins", "new words"), ("prose", "del", "old")]
    assert decks == {
        "after/slides.marked.html": [
            ("deck", "del", "removed"),
            ("deck", "ins", "added"),
        ]
    }
