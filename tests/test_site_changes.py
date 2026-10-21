"""Tests for marking a rendered site's changes on its own pages."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/asta-tools/skills/workspace/assets/site-changes.py"
)


def page(body, title="Page", extra=""):
    return (
        f'<html><head><meta name="generator" content="quarto-1.7.29"><title>{title}'
        f"</title></head><body>{extra}<main id=\"quarto-document-content\">{body}</main>"
        "</body></html>"
    )


def site(root, pages):
    for rel, doc in pages.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc, encoding="utf-8")


def mark(old, new, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--new", str(new), "--compare",
         "in this pull request", str(old), *extra],
        capture_output=True, text=True, check=True,
    )


def test_a_changed_page_carries_its_marks_and_an_unchanged_one_none(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    site(old, {
        "index.html": page("<p>The same words.</p>"),
        "review/index.html": page("<p>Attention replaced recurrence.</p>"),
    })
    site(new, {
        "index.html": page("<p>The same words.</p>"),
        "review/index.html": page("<p>Attention largely replaced recurrence.</p>"),
        "notes.html": page("<p>A new page.</p>", title="Notes"),
    })
    result = mark(old, new, "--on")
    assert "in this pull request: 2 pages" in result.stdout
    index = json.loads((new / "_changes/index.json").read_text())
    assert index == {"on": True, "comparisons": [
        {"id": "c0", "label": "in this pull request", "total": 2}]}
    manifest = json.loads((new / "_changes/c0/manifest.json").read_text())
    assert manifest["pages"]["review/index.html"]["marks"] >= 1
    assert manifest["pages"]["notes.html"]["state"] == "new"
    assert "index.html" not in manifest["pages"]
    # Saved as text, so that a site's link check doesn't read it as a page.
    marked = (new / "_changes/c0/pages/review/index.html.txt").read_text()
    assert "<ins" in marked and "largely" in marked
    assert not (new / "_changes/c0/pages/review/index.html").exists()


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
    site(new, {
        "index.html": page("<p>Two.</p>"),
        "artifacts/run.html": report.replace("copied", "copied again"),
        "paper/html/index.html": page("<p>Viewer</p>", extra='<div data-paper-preview="x">'),
    })
    mark(old, new)
    manifest = json.loads((new / "_changes/c0/manifest.json").read_text())
    assert set(manifest["pages"]) == {"index.html"}
    # Every rendered page loads the script, the paper's included; copied HTML doesn't.
    assert "_changes/changes.js" in (new / "index.html").read_text()
    assert "../../_changes/changes.js" in (new / "paper/html/index.html").read_text()
    assert "_changes" not in (new / "artifacts/run.html").read_text()
    # Off unless asked for.
    assert json.loads((new / "_changes/index.json").read_text())["on"] is False


def test_the_report_already_made_is_the_overview_and_a_rerun_adds_no_second_tag(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    site(old, {"index.html": page("<p>One.</p>")})
    site(new, {"index.html": page("<p>Two.</p>")})
    (new / "what-changed.html").write_text("the preview's report")
    mark(old, new, "--on")
    mark(old, new, "--on")
    assert (new / "what-changed.html").read_text() == "the preview's report"
    manifest = json.loads((new / "_changes/c0/manifest.json").read_text())
    assert manifest["overview"] == "what-changed.html"
    assert (new / "index.html").read_text().count("_changes/changes.js") == 1


def test_a_preview_and_the_demo_name_their_comparison_alike():
    root = Path(__file__).parents[1]
    workflow = (root / ".github/workflows/workspace-quarto-site.yml").read_text()
    demo = (root / "examples/workspace/scripts/refresh-demo.py").read_text()
    assert '--compare "in this pull request" "$baseline" --on' in workflow
    assert 'PREVIEW_LABEL = "in this pull request"' in demo


def test_a_preview_marks_nothing_without_a_baseline_or_with_its_own_report_alone():
    workflow = (
        Path(__file__).parents[1] / ".github/workflows/workspace-quarto-site.yml"
    ).read_text()
    marking = workflow[workflow.index("Each page then shows its changes in place"):]
    marking = marking[: marking.index("--compare")]
    # Before the first deploy, and for a project's own report without its own
    # marker, which the shipped one couldn't load, the step stops first.
    assert '[ "$baseline_label" = "no deployed baseline" ]' in marking
    assert '[ "$gen" = scripts/what-changed.py ]' in marking
    assert marking.index("no deployed baseline") < marking.index("curl")
