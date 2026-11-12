"""Exercise the real rendered-slide diff using the built example deck."""

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from site_server import _serve

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "plugins/asta-tools/skills/workspace/assets"
spec = importlib.util.spec_from_file_location("changed", ASSETS / "what-changed.py")
changed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changed)


def copy_site(site, destination):
    # A published preview already carries its own What changed output. Exclude
    # only these top-level outputs, preserving real nested pages/assets like
    # slides/demo/ in the deck under test.
    generated = {
        "demo",
        "what-changed.html",
        "what-changed-decks",
        "what-changed-assets",
    }

    def ignore(directory, names):
        return generated.intersection(names) if Path(directory) == site else set()

    shutil.copytree(site, destination, ignore=ignore)


def check(site, artifacts):
    from playwright.sync_api import sync_playwright

    artifacts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for side in ("old", "new"):
            copy_site(site, root / side)
        deck = Path("slides/attention/slides.html")
        original = (root / "old" / deck).read_text()
        slides = changed.reveal_slides(original)
        assert len(slides) >= 5
        # Root-relative images resolve at each site origin, including lazy-loaded images.
        image = '<img data-src="/review-image.svg" alt="Review image" width="300" height="100">'
        baseline = original.replace(slides[2]["body"], slides[2]["body"] + image, 1)
        after = baseline.replace(
            slides[1]["body"], slides[1]["body"].replace("</h", " revised</h", 1), 1
        )
        after = after.replace(
            slides[-1]["body"], "<h2>A new slide</h2><p>New content.</p>", 1
        )
        # A new id makes this an addition/removal, rather than an edit.
        after = after.replace('id="' + slides[-1]["id"] + '"', 'id="review-added"', 1)
        for side, document, color in [
            ("old", baseline, "#105257"),
            ("new", after, "#ffa31c"),
        ]:
            (root / side / deck).write_text(document)
            (root / side / "review-image.svg").write_text(
                f'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100"><rect width="300" height="100" fill="{color}"/></svg>'
            )
        out = root / "new/what-changed.html"
        result = subprocess.run(
            [
                sys.executable,
                str(ASSETS / "what-changed.py"),
                "--old",
                str(root / "old"),
                "--new",
                str(root / "new"),
                "--out",
                str(out),
                "--render-decks",
                str(root / "new/what-changed-decks"),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "slides as text" not in result.stderr, result.stderr
        server = _serve(str(root / "new"))
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.goto(
                    f"http://127.0.0.1:{server.server_address[1]}/what-changed.html"
                )
                page.locator(".deck-review").wait_for()
                assert page.locator(".dr-changed").count() > 0
                assert page.locator(".dr-look").count() > 0
                assert page.locator(".dr-new").count() > 0
                assert page.locator(".dr-removed").count() == 1
                assert page.locator("details.dr-unchanged").count() > 0
                # Each view hides the other views' frames (display: none), which
                # never become stable, so only the shown frames are waited on.
                for view in ["before", "clean", "marked"]:
                    page.locator(f'.dr-seg button[data-v="{view}"]').click()
                    frames = page.locator(".dr-slide iframe:visible").all()
                    assert frames, view
                    for frame in frames:
                        frame.scroll_into_view_if_needed()
                        # Frames are sandboxed: read them through Playwright.
                        frame.element_handle().content_frame().wait_for_function(
                            "() => !!window.Reveal && Reveal.isReady()"
                        )
                assert (
                    page.locator("iframe")
                    .first.content_frame.locator(".reveal")
                    .count()
                    == 1
                )
                page.screenshot(path=str(artifacts / "deck-review-live.png"))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


def large_deck(original, slides, count=60):
    """``original`` with ``count`` more slides, each with a large inline image."""
    import base64

    # Distinct images, as in a real talk: the browser cannot share one decode.
    def slide(i):
        pad = f"<!-- {i} " + "x" * 150_000 + " -->"
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100">'
            f'<rect width="300" height="100" fill="#{(i * 4099) % 0xFFFFFF:06x}"/>{pad}</svg>'
        )
        data = base64.b64encode(svg.encode()).decode()
        return (
            f'<section id="big-{i}"><h2>Large deck slide {i}</h2>'
            f'<p>Text on slide {i}.</p><img src="data:image/svg+xml;base64,{data}">'
            "</section>"
        )

    start = slides[0]["span"][0]
    return original[:start] + "".join(slide(i) for i in range(count)) + original[start:]


def check_large_deck(site, artifacts):
    """A deck added whole: every slide shows within seconds of scrolling to it."""
    import time

    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for side in ("old", "new"):
            copy_site(site, root / side)
        deck = Path("slides/attention/slides.html")
        original = (root / "new" / deck).read_text()
        slides = changed.reveal_slides(original)
        big = large_deck(original, slides)
        assert len(big) > 9_000_000
        (root / "old" / deck).unlink()
        (root / "new" / deck).write_text(big)
        out = root / "new/what-changed.html"
        result = subprocess.run(
            [
                sys.executable,
                str(ASSETS / "what-changed.py"),
                "--old",
                str(root / "old"),
                "--new",
                str(root / "new"),
                "--out",
                str(out),
                "--render-decks",
                str(root / "new/what-changed-decks"),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "slides as text" not in result.stderr, result.stderr
        # Whatever the page loads for a frame is a small document, not the deck.
        frames = (root / "new/what-changed-decks/after").rglob("*.frame-*.html")
        sizes = [path.stat().st_size for path in frames]
        assert len(sizes) >= 60 and max(sizes) < 400_000, max(sizes)
        server = _serve(str(root / "new"))
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.goto(
                    f"http://127.0.0.1:{server.server_address[1]}/what-changed.html"
                )
                page.locator(".deck-review").wait_for()
                cards = page.locator(".dr-new .dr-pair figure:visible iframe").all()
                assert len(cards) >= 60, len(cards)
                started = time.monotonic()
                for frame in cards:
                    frame.scroll_into_view_if_needed(timeout=5000)
                    # Its own slide, sharp and live, a few seconds after scrolling to it.
                    frame.element_handle().content_frame().wait_for_function(
                        "id => !!window.Reveal && Reveal.isReady()"
                        " && Reveal.getCurrentSlide().id === id",
                        arg=frame.get_attribute("data-dr-slide-id"),
                        timeout=10000,
                    )
                    # The page still answers while frames load.
                    began = time.monotonic()
                    page.evaluate("() => document.body.clientHeight")
                    assert time.monotonic() - began < 2
                print(
                    f"All {len(cards)} frames ready in {time.monotonic() - started:.1f} s"
                )
                page.screenshot(path=str(artifacts / "deck-review-large.png"))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


def check_external_font(site, artifacts):
    """A deck font loaded from a file (embed-resources: false) works in a frame."""
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for side in ("old", "new"):
            copy_site(site, root / side)
            shutil.copy(
                ASSETS / "_extensions/asta-theme/fonts/Manrope.woff2",
                root / side / "review-font.woff2",
            )
        deck = Path("slides/attention/slides.html")
        original = (root / "old" / deck).read_text()
        slides = changed.reveal_slides(original)
        face = (
            '<style>@font-face{font-family:"Review Font";'
            'src:url(/review-font.woff2) format("woff2")}'
            '.reveal .slides section h2{font-family:"Review Font",serif}</style>'
        )
        head = re.search(r"</head\s*>", original, re.I)
        with_font = original[: head.start()] + face + original[head.start() :]
        (root / "old" / deck).write_text(with_font)
        after = with_font.replace(
            slides[1]["body"], slides[1]["body"].replace("</h", " revised</h", 1), 1
        )
        assert after != with_font
        (root / "new" / deck).write_text(after)
        out = root / "new/what-changed.html"
        subprocess.run(
            [
                sys.executable,
                str(ASSETS / "what-changed.py"),
                "--old",
                str(root / "old"),
                "--new",
                str(root / "new"),
                "--out",
                str(out),
                "--render-decks",
                str(root / "new/what-changed-decks"),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        server = _serve(str(root / "new"))
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.goto(
                    f"http://127.0.0.1:{server.server_address[1]}/what-changed.html"
                )
                page.locator(".deck-review").wait_for()
                frames = page.locator(".dr-slide iframe:visible").all()
                assert frames
                for frame in frames:
                    assert frame.get_attribute("sandbox") == "allow-scripts"
                    frame.scroll_into_view_if_needed()
                    inner = frame.element_handle().content_frame()
                    inner.wait_for_function("() => !!window.Reveal && Reveal.isReady()")
                    # A face that failed to load (no CORS header for Origin: null)
                    # still passes document.fonts.check(): load it, read its status.
                    status = inner.evaluate(
                        """async () => {
                            const faces = [...document.fonts].filter(
                                f => f.family.replace(/"/g, "") === "Review Font");
                            await Promise.allSettled(faces.map(f => f.load()));
                            return faces.map(f => f.status);
                        }"""
                    )
                    assert status == ["loaded"], status
                    assert inner.evaluate(
                        "() => document.fonts.check('16px \"Review Font\"')"
                    )
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
    check_large_deck(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
    check_external_font(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
