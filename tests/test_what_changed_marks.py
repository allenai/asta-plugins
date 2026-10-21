"""Tests for what-changed.py's --mark: each page shows its own changes in place."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/asta-tools/skills/workspace/assets/what-changed.py"
)


def load_report():
    spec = importlib.util.spec_from_file_location("what_changed", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def page(body, title="Page", extra=""):
    return (
        f'<html><head><meta name="generator" content="quarto-1.7.29"><title>{title}'
        f'</title></head><body>{extra}<main id="quarto-document-content">{body}</main>'
        "</body></html>"
    )


def site(root, pages):
    for rel, doc in pages.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc, encoding="utf-8")


def args(old, new, *extra):
    # The report goes beside the site, as a preview writes it before moving it in.
    out = new.parent / "what-changed.html"
    return [
        "--old",
        str(old),
        "--new",
        str(new),
        "--out",
        str(out),
        "--mark",
        "in this pull request",
        *extra,
    ]


def mark(old, new, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args(old, new, *extra)],
        capture_output=True,
        text=True,
        check=True,
    )


def test_a_changed_page_carries_its_marks_and_an_unchanged_one_none(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    site(
        old,
        {
            "index.html": page("<p>The same words.</p>"),
            "review/index.html": page("<p>Attention replaced recurrence.</p>"),
        },
    )
    site(
        new,
        {
            "index.html": page("<p>The same words.</p>"),
            "review/index.html": page("<p>Attention largely replaced recurrence.</p>"),
            "notes.html": page("<p>A new page.</p>", title="Notes"),
        },
    )
    result = mark(old, new, "--on")
    assert "marked 2 pages, 0 papers, 0 removed in this pull request" in result.stderr
    index = json.loads((new / "_changes/index.json").read_text())
    assert index == {
        "on": True,
        "comparisons": [{"id": "c0", "label": "in this pull request", "total": 2}],
    }
    manifest = json.loads((new / "_changes/c0/manifest.json").read_text())
    assert manifest["overview"] == "what-changed.html"
    assert manifest["pages"]["review/index.html"]["marks"] >= 1
    assert manifest["pages"]["notes.html"]["state"] == "new"
    assert "index.html" not in manifest["pages"]
    # Saved as text, so that a site's link check doesn't read it as a page.
    marked = (new / "_changes/c0/pages/review/index.html.txt").read_text()
    assert "<ins" in marked and "largely" in marked
    assert not (new / "_changes/c0/pages/review/index.html").exists()


def test_without_mark_the_report_alone_is_written(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    site(old, {"index.html": page("<p>One.</p>")})
    site(new, {"index.html": page("<p>Two.</p>")})
    out = tmp_path / "report.html"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--old",
            str(old),
            "--new",
            str(new),
            "--out",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    assert out.is_file() and not (new / "_changes").exists()
    assert "_changes" not in (new / "index.html").read_text()


def test_a_marked_page_keeps_what_the_page_relies_on_but_no_scripts(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    before = (
        '<h2 id="claims">Claims</h2><p>See <a href="#ref-v" role="doc-biblioref" '
        'data-cites="v">Vaswani</a>; <span class="ev" tabindex="0">a claim</span>.</p>'
    )
    after = before.replace("a claim", "a stronger claim") + (
        '<p onclick="steal()" style="color: red">Late <img src=x onerror="steal()">'
        "</p><script>steal()</script>"
    )
    site(old, {"index.html": page(before)})
    site(new, {"index.html": page(after)})
    mark(old, new)
    marked = (new / "_changes/c0/pages/index.html.txt").read_text()
    # Anchors, citations' data and keyboard focus stay, so that links, hovers
    # and focus work on the marked page as on the page itself.
    for kept in ('id="claims"', 'data-cites="v"', 'tabindex="0"', 'style="color: red"'):
        assert kept in marked, kept
    for dropped in ("onclick", "onerror", "<script", "steal()</"):
        assert dropped not in marked, dropped


def test_the_script_goes_before_the_documents_own_closing_tag(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    site(old, {"index.html": page("<p>One.</p>")})
    quoted = "<script>const tail = '</body>';</script>"
    site(new, {"index.html": page("<p>Two.</p>", extra=quoted)})
    mark(old, new)
    doc = (new / "index.html").read_text()
    assert quoted in doc
    assert doc.index("_changes/changes.js") > doc.index(quoted)


def test_only_pages_the_site_renders_are_compared_and_load_the_script(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    report = "<html><body><main>Run report, copied through</main></body></html>"
    site(old, {"index.html": page("<p>One.</p>"), "artifacts/run.html": report})
    site(
        new,
        {
            "index.html": page("<p>Two.</p>"),
            "artifacts/run.html": report.replace("copied", "copied again"),
            "paper/html/index.html": page(
                "<p>Viewer</p>", extra='<div data-paper-preview="x">'
            ),
        },
    )
    mark(old, new)
    manifest = json.loads((new / "_changes/c0/manifest.json").read_text())
    assert set(manifest["pages"]) == {"index.html"}
    # Every rendered page loads the script, the paper's included; copied HTML doesn't.
    assert "_changes/changes.js" in (new / "index.html").read_text()
    assert "../../_changes/changes.js" in (new / "paper/html/index.html").read_text()
    assert "_changes" not in (new / "artifacts/run.html").read_text()
    # Off unless asked for.
    assert json.loads((new / "_changes/index.json").read_text())["on"] is False


def test_a_page_whose_only_change_is_unseen_counts_with_nothing_marked(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    site(old, {"index.html": page("<p>One.</p>"), "b.html": page("<p>Bee.</p>")})
    site(
        new,
        {
            "index.html": page("<p>Two.</p>"),
            "b.html": page('<p>Bee.<span id="anchor"></span></p>'),
        },
    )
    mark(old, new)
    manifest = json.loads((new / "_changes/c0/manifest.json").read_text())
    # As the report lists it, so that the sidebar and its count agree with it.
    assert manifest["pages"]["b.html"] == {
        "state": "changed",
        "title": "Page",
        "unseen": True,
    }
    assert manifest["total"] == 2
    assert not (new / "_changes/c0/pages/b.html.txt").exists()
    assert "p-b-html" in (new.parent / "what-changed.html").read_text()


def test_a_copied_page_in_another_encoding_doesnt_stop_the_marks(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    site(old, {"index.html": page("<p>One.</p>")})
    site(new, {"index.html": page("<p>Two.</p>")})
    report = "<html><body>Résumé of the run</body></html>"
    for root in (old, new):
        (root / "artifacts").mkdir()
        (root / "artifacts/run.html").write_bytes(report.encode("latin-1"))
    result = mark(old, new)
    assert "marked 1 pages" in result.stderr
    assert "_changes/changes.js" in (new / "index.html").read_text()
    assert (new / "artifacts/run.html").read_bytes() == report.encode("latin-1")


def test_a_rerun_adds_no_second_tag(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    site(old, {"index.html": page("<p>One.</p>")})
    site(new, {"index.html": page("<p>Two.</p>")})
    mark(old, new, "--on")
    mark(old, new, "--on")
    assert (new / "index.html").read_text().count("_changes/changes.js") == 1


def test_a_preview_and_the_demo_mark_with_the_same_words():
    root = Path(__file__).parents[1]
    workflow = (root / ".github/workflows/workspace-quarto-site.yml").read_text()
    demo = (root / "examples/workspace/scripts/refresh-demo.py").read_text()
    assert 'mark=(--mark "in this pull request" --on)' in workflow
    assert 'PREVIEW_LABEL = "in this pull request"' in demo


def test_a_preview_marks_nothing_without_a_baseline_or_with_its_own_report():
    workflow = (
        Path(__file__).parents[1] / ".github/workflows/workspace-quarto-site.yml"
    ).read_text()
    # Before the first deploy, and for a project's own report, which needn't
    # know how, the report runs without --mark.
    assert (
        'if [ "$gen" != scripts/what-changed.py ] && '
        '[ "$baseline_label" != "no deployed baseline" ]; then\n'
        '            mark=(--mark "in this pull request" --on)'
    ) in workflow
    assert '"${mark[@]}"' in workflow


def test_a_run_that_fails_partway_leaves_the_site_as_it_found_it(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    site(old, {"index.html": page("<p>One.</p>"), "b.html": page("<p>Bee.</p>")})
    site(new, {"index.html": page("<p>Two.</p>"), "b.html": page("<p>Bees.</p>")})
    # A page already tagged by an earlier run (a nested site copy, say) isn't
    # this run's to untag.
    earlier = page("<p>Kept.</p>").replace(
        "</body>",
        '<!-- what-changed marks --><link rel="stylesheet" '
        'href="_changes/changes.css"><script src="_changes/changes.js" defer>'
        "</script></body>",
    )
    site(new, {"c.html": earlier})
    before = {p.name: p.read_text() for p in new.glob("*.html")}
    report = load_report()
    tag_pages = report.tag_pages

    def tag_then_fail(root, tagged):
        tag_pages(root, tagged)
        raise OSError("disk full")

    monkeypatch.setattr(report, "tag_pages", tag_then_fail)
    report.main(args(old, new))
    # The report stands; no marks are half-made: neither their files nor a
    # page's tags for them; and the earlier page keeps its own.
    assert (new.parent / "what-changed.html").is_file()
    assert not (new / "_changes").exists()
    assert {p.name: p.read_text() for p in new.glob("*.html")} == before
    assert not list(new.glob("*.what-changed-tmp"))


def test_a_cleanup_that_fails_still_leaves_the_report(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    site(old, {"index.html": page("<p>One.</p>")})
    site(new, {"index.html": page("<p>Two.</p>")})
    report = load_report()

    def fail(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(report, "tag_pages", fail)
    monkeypatch.setattr(report, "untag_pages", fail)
    report.main(args(old, new))
    assert (new.parent / "what-changed.html").is_file()


def test_the_page_the_report_takes_the_place_of_isnt_counted(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    # A project page named for the report, in both sites, with other text.
    site(
        old,
        {"index.html": page("<p>One.</p>"), "what-changed.html": page("<p>Old.</p>")},
    )
    site(
        new,
        {"index.html": page("<p>Two.</p>"), "what-changed.html": page("<p>New.</p>")},
    )
    mark(old, new)
    manifest = json.loads((new / "_changes/c0/manifest.json").read_text())
    assert set(manifest["pages"]) == {"index.html"} and manifest["removed"] == []
    # Written into the new site, the report doesn't list the old page as removed.
    load_report().main(
        ["--old", str(old), "--new", str(new), "--out", str(new / "what-changed.html")]
    )
    assert "p-what-changed-html" not in (new / "what-changed.html").read_text()
