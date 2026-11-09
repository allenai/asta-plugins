"""Run the local What changed on the example workspace with the demo PR's sample
edit applied uncommitted: the page must show every content type it touches."""

import subprocess
import sys
from pathlib import Path

from site_server import _serve

ROOT = Path(__file__).resolve().parents[2]
THEMED_JS = (
    "() => ['bootstrap', 'asta-theme'].every(name => [...document.styleSheets]"
    ".some(s => s.href && s.href.includes(name) && s.cssRules.length))"
)
POP_SHOWN_JS = (
    "ev => { const p = ev.querySelector(':scope > .ev-pop');"
    " if (!p) return false; const s = getComputedStyle(p);"
    " return s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0; }"
)
NAV_SHOWN_JS = (
    "() => [...document.querySelectorAll('.reveal .controls, .slide-menu-button')]"
    ".some(e => getComputedStyle(e).display !== 'none' && e.getClientRects().length)"
)


def check_evidence(page, missing):
    """Every claim on a changed page opens its quote on hover and on focus."""
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    claims = page.locator(".wc-scope .ev")
    for i in range(claims.count()):
        ev = claims.nth(i)
        ev.scroll_into_view_if_needed()
        ev.hover()
        try:
            page.wait_for_function(POP_SHOWN_JS, arg=ev.element_handle(), timeout=2000)
            hovered = True
        except Exception:
            hovered = False
        page.mouse.move(0, 0)
        ev.focus()
        try:
            page.wait_for_function(POP_SHOWN_JS, arg=ev.element_handle(), timeout=2000)
            focused = True
        except Exception:
            focused = False
        if not (hovered and focused):
            missing.append(f"evidence claim {i + 1}'s quote on hover/focus")


FRAME_FIT_JS = """() => {
  const box = Reveal.getSlidesElement().getBoundingClientRect();
  const scale = Math.min(innerWidth / 1600, innerHeight / 900);
  const expected = [(innerWidth - 1600 * scale) / 2,
    (innerHeight - 900 * scale) / 2, 1600 * scale, 900 * scale];
  return Reveal.getConfig().margin === 0 &&
    [box.left, box.top, box.width, box.height].every(
      (value, i) => Math.abs(value - expected[i]) <= 1.5);
}"""


def check_frames(page, missing):
    """Every shown slide fills its frame and offers no slide navigation."""
    for review_number, review in enumerate(page.locator(".deck-review").all(), 1):
        # Include the unchanged slides a reviewer can unfold, in each actual view.
        for fold in review.locator("details.dr-unchanged").all():
            fold.evaluate("node => node.open = true")
        for view in ("marked", "clean", "before"):
            review.locator(f'.dr-seg button[data-v="{view}"]').click()
            for i, el in enumerate(review.locator("iframe:visible").all(), 1):
                label = f"deck {review_number}, {view}, slide frame {i}"
                el.scroll_into_view_if_needed()
                frame = el.element_handle().content_frame()
                try:
                    frame.wait_for_function(
                        "() => window.Reveal && Reveal.isReady && Reveal.isReady()",
                        timeout=15000,
                    )
                except Exception:
                    missing.append(f"{label} becoming ready")
                    continue
                if frame.evaluate(NAV_SHOWN_JS):
                    missing.append(f"{label} without Reveal controls")
                try:
                    frame.wait_for_function(FRAME_FIT_JS, timeout=5000)
                except Exception:
                    missing.append(f"{label} filling its frame")


def check_site(site, artifacts):
    """Shared acceptance contract for local reports and the published demo."""
    from playwright.sync_api import sync_playwright

    artifacts.mkdir(parents=True, exist_ok=True)
    html = (site / "what-changed.html").read_text()
    missing = []
    if not (site / "paper-previews/paper/what-changed.pdf").is_file() or (
        "paper-previews/paper/what-changed.pdf" not in html
    ):
        missing.append("the marked paper diff")
    if 'class="deck-live deck-review"' not in html:
        missing.append("the changed slide")
    if "lit-review/index.html" not in html:
        missing.append("the literature review's prose diff")
    elif "wc-ev-chip" not in html and "ev-pop" not in html:
        missing.append("the literature review's evidence")
    server = _serve(str(site))
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/what-changed.html")
            if not page.evaluate(THEMED_JS):
                missing.append("the site's theme")
            if page.locator(".deck-review").count():
                page.locator(".deck-review").first.wait_for()
                if page.locator(".dr-changed, .dr-new, .dr-look").count() == 0:
                    missing.append("the changed slide")
                check_frames(page, missing)
            check_evidence(page, missing)
            page.screenshot(
                path=str(artifacts / "local-what-changed-demo.png"), full_page=True
            )
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    assert not missing, "What changed is missing " + ", ".join(missing)


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, nargs="?")
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("--site", type=Path, help="Check an already-built report")
    args = parser.parse_args()
    if args.site:
        if args.project:
            parser.error("use a project or --site, not both")
        site = args.site.resolve()
    else:
        if args.project is None:
            parser.error("a project or --site is required")
        project = args.project.resolve()
        result = subprocess.run(
            ["asta", "workspace", "what-changed", "--timings", "HEAD"],
            cwd=project,
            capture_output=True,
            text=True,
        )
        print(result.stderr, file=sys.stderr)
        assert result.returncode == 0, result.stdout
        site = project / ".asta/cache/what-changed"
    check_site(site, args.artifacts.resolve())


if __name__ == "__main__":
    main()
