"""Tests for the rendered Quarto preview diff generator."""

import importlib.util
import re
from pathlib import Path


def _underline_contexts(css):
    """Selector text preceding every `text-decoration: underline` in the output.

    CSS comments (which document the rules and quote CSS verbatim) are stripped
    first so prose about underlines isn't mistaken for an actual rule.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return re.findall(r"([^{}]*)\{[^{}]*text-decoration:\s*underline", css)


def _only_underline_on_hover(css):
    """No resting underline anywhere — underline is only ever a :hover/:focus cue."""
    return all(":hover" in ctx or ":focus" in ctx for ctx in _underline_contexts(css))


SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/asta-tools/skills/workspace/assets/what-changed.py"
)
SPEC = importlib.util.spec_from_file_location("what_changed", SCRIPT)
WHAT_CHANGED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WHAT_CHANGED)


def test_build_reuses_quarto_theme_and_marks_changes_accessibly(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = """<!doctype html><html><head>
      <link href="site_libs/bootstrap/bootstrap.min.css" rel="stylesheet">
      <style>.quarto-title {{ font-weight: 700; }}</style>
      </head><body><main><p>{text}</p></main></body></html>"""
    (old / "index.html").write_text(shell.format(text="Old text"))
    (new / "index.html").write_text(shell.format(text="New text"))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert 'href="site_libs/bootstrap/bootstrap.min.css"' in result
    assert ".quarto-title { font-weight: 700; }" in result
    assert (
        'class="page-columns page-rows-contents page-layout-article wc-scope"' in result
    )
    assert "<del>Old</del>" in result
    assert "<ins>New</ins>" in result
    # Insertions are background-only (no underline); deletions keep strikethrough.
    # The only `text-decoration: underline` allowed is the :hover/:focus link
    # affordance — never a resting underline on insertions or links.
    assert _only_underline_on_hover(result), _underline_contexts(result)
    assert "text-decoration: line-through" in result
    assert "--wc-tag-fg: #fff" in result
    assert ".wc-scope nav.toc .tag" in result
    assert (
        ".wc-scope .tag.changed { background: var(--wc-changed); "
        "color: var(--wc-tag-fg); }" in result
    )


def test_evidence_claim_underline_is_legible_on_the_diff(tmp_path):
    """Evidence gets a perceptible dotted rule without restoring insertion lines.

    The extension's default 1px, 32%-opacity border is too subtle against the
    diff's green insertion tint, so the generator strengthens that one cue with
    an information-blue rule. The claim itself must also survive the word-diff
    intact.
    """
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "index.html").write_text(
        "<html><head></head><body><main><p>Baseline.</p></main></body></html>"
    )
    # The evidence extension injects its `.ev` styling into the page <head>; the
    # diff reuses the template page's head styles, so it must carry through.
    (new / "index.html").write_text(
        "<html><head><style>.ev { border-bottom: 1px dotted rgba(0, 0, 0, 0.32); }"
        "</style></head><body><main>"
        '<p>NatureBench has <span class="ev" title="evidence">90 tasks</span>.</p>'
        "</main></body></html>"
    )

    result = WHAT_CHANGED.build(old, new, "", "PR #2")

    # No old amber highlight or resting insertion/link underline competes with the
    # evidence cue. The diff strengthens only the evidence claim's dotted rule.
    assert "--wc-ev-bg" not in result
    assert "box-shadow: inset 0 -2px 0" not in result
    assert _only_underline_on_hover(result), _underline_contexts(result)
    assert ".wc-scope .ev { border-bottom: 2px dotted #2a88ef; }" in result
    # The extension's own `.ev` styling still survives via the reused head CSS.
    assert ".ev { border-bottom: 1px dotted rgba(0, 0, 0, 0.32); }" in result
    # The claim survives the word-diff with its class intact.
    assert 'class="ev"' in result
    assert "90 tasks" in result


def test_links_are_not_underlined_at_rest_on_the_diff(tmp_path):
    """The reused theme carries Bootstrap's default `a { text-decoration: underline }`.
    On the diff that underlines every citation, crossref (e.g. "Table 1") and bare
    URL, and inside an inserted run those links take the green ins colour — reading
    as green underlines scattered across the page. The generator suppresses the
    resting link underline (GitHub's diff view does the same) so the dotted `.ev`
    cue is the only resting underline; the underline returns on hover/focus."""
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "index.html").write_text(
        "<html><head></head><body><main><p>Baseline.</p></main></body></html>"
    )
    (new / "index.html").write_text(
        "<html><head></head><body><main>"
        '<p>See <a href="#tbl-x">Table 1</a> and '
        '<a href="https://arxiv.org/abs/1">the paper</a>.</p>'
        "</main></body></html>"
    )

    result = WHAT_CHANGED.build(old, new, "", "PR #3")

    # Resting link underline is suppressed, restored only on hover/focus.
    assert ".wc-scope a { text-decoration: none; }" in result
    assert (
        ".wc-scope a:hover, .wc-scope a:focus { text-decoration: underline; }" in result
    )
    assert _only_underline_on_hover(result), _underline_contexts(result)
    # The links themselves still render (identifiable by colour), just not underlined.
    assert 'href="#tbl-x"' in result


def test_nested_template_stylesheet_is_rebased_to_preview_root(tmp_path):
    new = tmp_path / "new"
    new.mkdir()
    nested = new / "guide"
    nested.mkdir()
    (nested / "page.html").write_text(
        '<html><head><link rel="stylesheet" href="../site_libs/theme.css">'
        "</head><body><main>Content</main></body></html>"
    )

    doc, depth = WHAT_CHANGED.pick_template(WHAT_CHANGED.list_pages(new))
    theme = WHAT_CHANGED.extract_theme_css(doc, depth)

    assert depth == 1
    assert 'href="site_libs/theme.css"' in theme


def test_dark_quarto_theme_selects_dark_diff_palette(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = """<html><head><link id="quarto-bootstrap" data-mode="dark"
      rel="stylesheet" href="site_libs/bootstrap.css"></head>
      <body><main><p>{text}</p></main></body></html>"""
    (old / "index.html").write_text(shell.format(text="Old"))
    (new / "index.html").write_text(shell.format(text="New"))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert "wc-scope wc-dark" in result
    assert "--wc-tag-fg: #0d1117" in result


def test_output_ships_client_side_folding_but_keeps_full_content(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    filler = "".join(
        f"<p>Untouched paragraph number {i} with enough words to matter.</p>"
        for i in range(8)
    )
    shell = "<html><head></head><body><main>{body}</main></body></html>"
    (old / "index.html").write_text(shell.format(body=filler + "<p>original line</p>"))
    (new / "index.html").write_text(shell.format(body=filler + "<p>replaced line</p>"))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    # The folding is progressive enhancement: the script ships and the styling
    # for the collapsed hunks is present.
    assert "details.wc-fold" in result
    assert "Expand all unchanged" in result
    assert "DOMContentLoaded" in result
    # A single rendered element can hold a whole section, so long singleton
    # blocks and oversized neighboring context are folded by default.
    assert "var MIN_BLOCKS = 1" in result
    assert "var MAX_CONTEXT_CHARS = 500" in result
    assert "kids[j].textContent.length <= MAX_CONTEXT_CHARS" in result
    # ...but the server never pre-collapses, so no-JS reviewers still get
    # every unchanged paragraph verbatim.
    assert "Untouched paragraph number 7" in result
    # The server never pre-collapses; the DOM ships flat and JS folds it, so a
    # no-JS reviewer still sees every block and the markup stays valid.
    assert "<details" not in result
    assert "\\25B8" in result  # CSS chevron escape survives, not mangled to octal


def test_computed_page_is_linked_not_word_diffed_or_embedded(tmp_path):
    # A page carrying computed output (here a Plotly widget) must not be
    # word-diffed (fragile against volatile rendered markup) nor embedded whole
    # (that would run its scripts in the diff page). When its visible text
    # changes it is shown as a linked summary card with a static-text preview.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = (
        "<html><head></head><body><main>"
        "<p>Revenue was {figure}.</p>"
        '<div class="plotly-graph-div" id="{wid}"></div>'
        '<script type="application/json" data-for="{wid}">{{"x":[{x}]}}</script>'
        "</main></body></html>"
    )
    (old / "index.html").write_text(shell.format(figure="$1M", wid="a1b2", x="1,2,3"))
    (new / "index.html").write_text(shell.format(figure="$2M", wid="z9y8", x="4,5,6"))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    # Linked as an interactive page, not word-diffed: the current visible text
    # shows in the preview, the old value is gone, and none of the page's own
    # <script> is embedded into the diff document.
    assert "interactive page (linked)" in result
    assert "Revenue was $2M." in result
    assert "$1M" not in result
    assert "open the full page" in result
    assert 'type="application/json"' not in result


def test_new_self_contained_page_is_linked_and_carries_no_foreign_script(tmp_path):
    # A brand-new self-contained report (an empty container filled by one large
    # inline data payload — no framework marker) must be linked with a card, not
    # dumped whole: embedding its multi-KB script would bloat the page and, with
    # several such pages, collide.
    new = tmp_path / "new"
    new.mkdir()
    payload = "const DATA_B64='%s';" % ("A" * 40000)
    (new / "report.html").write_text(
        "<html><head></head><body>"
        '<h1>Trajectories</h1><div class="tiles" id="tiles"></div>'
        f"<script>{payload}document.getElementById('tiles').textContent='x';</script>"
        "</body></html>"
    )

    result = WHAT_CHANGED.build(tmp_path / "old", new, "", "PR #1")
    (tmp_path / "old").mkdir(exist_ok=True)

    assert "new page · interactive (linked)" in result
    assert "DATA_B64" not in result  # the payload is not embedded
    assert "Trajectories" in result  # static text still previewed
    assert len(result) < 20000


def test_two_self_contained_pages_do_not_collide(tmp_path):
    # The core failure: two self-contained pages that declare the same top-level
    # identifiers and reuse the same element ids. Embedded whole they would throw
    # "identifier already declared" and leave duplicate ids; linked as cards they
    # carry no script and no widget ids, so nothing collides.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    page = (
        "<html><head></head><body>"
        '<h1>Report {n}</h1><div id="tiles"></div>'
        "<script>const DATA_B64='{blob}';const renderTiles=()=>{{}};</script>"
        "</body></html>"
    )
    (new / "a.html").write_text(page.format(n="A", blob="A" * 40000))
    (new / "b.html").write_text(page.format(n="B", blob="B" * 40000))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert result.count('id="tiles"') == 0
    assert "const DATA_B64" not in result
    assert result.count('class="page-diff new"') == 2
    assert "interactive (linked)" in result


def test_embedded_new_prose_page_is_stripped_of_scripts(tmp_path):
    # An ordinary new prose page is embedded inline (good) but any incidental
    # <script>/<style> it carries is stripped — the diff page runs only its own.
    new = tmp_path / "new"
    new.mkdir()
    (tmp_path / "old").mkdir()
    (new / "page.html").write_text(
        "<html><head></head><body><main>"
        "<p>Fresh prose paragraph.</p>"
        "<script>console.log('should not survive')</script>"
        "<style>.x{color:red}</style>"
        "</main></body></html>"
    )

    result = WHAT_CHANGED.build(tmp_path / "old", new, "", "PR #1")

    assert "Fresh prose paragraph." in result
    assert "should not survive" not in result
    assert ".x{color:red}" not in result


def test_computed_page_data_change_is_reported_even_when_static_text_is_same(tmp_path):
    # Same static text, but changed widget ids / payload: it must be reported.
    # Static text equality cannot prove that client-rendered output is unchanged.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = (
        "<html><head></head><body><main>"
        "<p>Stable prose.</p>"
        '<div class="plotly-graph-div" id="{wid}"></div>'
        '<script type="application/json" data-for="{wid}">{{"id":"{wid}"}}</script>'
        "</main></body></html>"
    )
    (old / "index.html").write_text(shell.format(wid="a1b2c3"))
    (new / "index.html").write_text(shell.format(wid="z9y8x7"))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert "changed · interactive page (linked)" in result
    assert "open the full page" in result


def test_partly_changed_inline_tag_never_wraps_a_lone_tag(tmp_path):
    # A bold wrapper added around text that already existed: the <strong> open
    # and close land in *insert* runs while the word between them stays *equal*.
    # The wrapper must not emit `<ins><strong></ins>` (a lone tag inside <ins>,
    # invalid even if browsers recover) — the half-in tag is emitted bare.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = "<html><head></head><body><main><p>{body}</p></main></body></html>"
    (old / "index.html").write_text(shell.format(body="Guide to research"))
    (new / "index.html").write_text(
        shell.format(body="<strong>Guide</strong> to research")
    )

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert "<ins><strong></ins>" not in result
    assert "<ins></strong></ins>" not in result
    # The bold markup is still applied around the word, just not highlighted.
    assert "<strong>Guide</strong>" in result


def test_fully_inserted_inline_pair_is_still_highlighted(tmp_path):
    # When both halves of an inline pair fall inside the same inserted run, the
    # pair is balanced and stays highlighted inside <ins> (valid nesting).
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = "<html><head></head><body><main><p>Intro. {body}</p></main></body></html>"
    (old / "index.html").write_text(shell.format(body=""))
    (new / "index.html").write_text(shell.format(body="<em>Brand new clause.</em>"))

    result = WHAT_CHANGED.build(old, new, "", "PR #1")

    assert "<ins><em>Brand new clause.</em></ins>" in result


def test_own_output_is_never_diffed_as_a_page(tmp_path):
    # A previous run's what-changed.html left in the tree (matched by basename)
    # or any page carrying the generator marker (matched by signature) must not
    # appear as a page in the diff — the generator never diffs its own output.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = "<html><head></head><body><main><p>{t}</p></main></body></html>"
    (old / "index.html").write_text(shell.format(t="Same prose."))
    (new / "index.html").write_text(shell.format(t="Same prose."))
    # A stale artifact from an earlier run, by conventional name...
    (new / "what-changed.html").write_text(
        f"<html><head>{WHAT_CHANGED.WHAT_CHANGED_META}"
        "<title>What changed &middot; PR #4</title></head>"
        '<body><div class="wc-scope"><main>diff</main></div></body></html>'
    )
    # ...and one renamed but still self-identifying by its generator marker.
    (new / "old-diff.html").write_text(
        f"<html><head>{WHAT_CHANGED.WHAT_CHANGED_META}<title>What changed</title>"
        "</head><body><main>stale diff</main></body></html>"
    )

    result = WHAT_CHANGED.build(
        old, new, "", "PR #5", out_path=new / "what-changed.html"
    )

    assert "No rendered content changed" in result
    assert "PR #4" not in result
    assert 'id="p-what-changed"' not in result
    assert "old-diff.html" not in result
    # And the page it emits self-identifies so a later run skips it too.
    assert WHAT_CHANGED.is_what_changed_artifact(result)


def test_same_named_legitimate_page_in_subdirectory_is_not_suppressed(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    (old / "guide").mkdir(parents=True)
    (new / "guide").mkdir(parents=True)
    shell = "<html><head></head><body><main><p>{t}</p></main></body></html>"
    (old / "guide" / "what-changed.html").write_text(shell.format(t="Before"))
    (new / "guide" / "what-changed.html").write_text(shell.format(t="After"))

    result = WHAT_CHANGED.build(
        old, new, "", "PR #5", out_path=new / "what-changed.html"
    )

    assert "guide/what-changed.html" in result
    assert "<del>Before</del>" in result
    assert "<ins>After</ins>" in result


def test_embedded_markup_is_strictly_sanitized(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (new / "index.html").write_text(
        """<html><head></head><body><main>
        <p id="duplicate" onclick="alert(1)">Safe <strong>prose</strong>.</p>
        <a href="java&#x73;cript:alert(1)">bad link</a>
        <img src="https://example.org/chart.png" onerror="alert(1)" alt="chart">
        <iframe srcdoc="<script>alert(1)</script>">hidden</iframe>
        <svg onload="alert(1)"><a href="javascript:alert(1)">svg</a></svg>
        <script src="https://evil.example/x.js">alert(1)</script>
        <style>@import url(https://evil.example/x.css)</style>
        </main></body></html>"""
    )

    result = WHAT_CHANGED.build(old, new, "", "PR #5")
    section = result.split('id="p-index-html"', 1)[1].split("</section>", 1)[0]

    assert "Safe <strong>prose</strong>." in section
    assert 'src="https://example.org/chart.png"' in section
    for forbidden in (
        "onclick",
        "onerror",
        "javascript:",
        "<iframe",
        "<svg",
        "<script",
        "<style",
        'id="duplicate"',
        "evil.example",
    ):
        assert forbidden not in section


def test_large_inline_style_does_not_make_static_page_interactive():
    content = "<style>" + ("x" * 25_000) + "</style><p>Static prose.</p>"

    assert not WHAT_CHANGED.is_script_heavy(content)


def test_markup_only_change_is_annotated_not_embedded(tmp_path):
    # PR #4's only edit to proposal.qmd was inserting an invisible cross-ref
    # anchor `[]{#contributions}` -> an empty <span id="contributions">. The
    # rendered text is unchanged, so the page must be annotated (naming the
    # anchor) and linked, not embedded whole tagged "changed" with nothing lit.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    body = "<h2>Overview</h2><p>Lots of unchanged prose here.</p>"
    shell = "<html><head></head><body><main>{b}</main></body></html>"
    (old / "proposal.html").write_text(
        shell.format(b=body + "<p>Our contributions:</p>")
    )
    (new / "proposal.html").write_text(
        shell.format(
            b=body + '<p><span id="contributions"></span>Our contributions:</p>'
        )
    )

    result = WHAT_CHANGED.build(old, new, "https://x/pr-5", "PR #5")

    assert "non-visible markup only" in result
    assert "anchor added: #contributions" in result
    assert "open the full page" in result
    # It is NOT rendered as a word-level prose diff: the page's own text is not
    # embedded, and the section body carries no highlighted runs.
    assert result.count("Lots of unchanged prose here.") == 0
    section = result.split('id="p-proposal-html"', 1)[1].split("</section>", 1)[0]
    assert "<ins>" not in section and "<del>" not in section


def test_visible_text_change_still_gets_a_full_word_diff(tmp_path):
    # Guard the branch boundary: a real visible edit on a prose page must still
    # produce an inline word diff, not the markup-only annotation.
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    shell = "<html><head></head><body><main><p>{t}</p></main></body></html>"
    (old / "index.html").write_text(shell.format(t="Synced 2026-05-17 today."))
    (new / "index.html").write_text(shell.format(t="Synced 2026-08-14 today."))

    result = WHAT_CHANGED.build(old, new, "", "PR #5")

    assert "<del>2026-05-17</del>" in result
    assert "<ins>2026-08-14</ins>" in result
    assert "non-visible markup only" not in result


def test_has_computed_output_detects_widgets_and_ignores_prose():
    assert WHAT_CHANGED.has_computed_output('<div class="cell-output">x</div>')
    assert WHAT_CHANGED.has_computed_output('<div class="observablehq"></div>')
    assert WHAT_CHANGED.has_computed_output(
        '<script type="application/json">{}</script>'
    )
    assert not WHAT_CHANGED.has_computed_output(
        "<p>Just prose with <a href='x'>a link</a> and <code>code</code>.</p>"
    )
