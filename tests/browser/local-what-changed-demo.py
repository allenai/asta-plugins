"""Run the local What changed on the example workspace with the demo PR's sample
edit applied uncommitted: the page must show every content type it touches."""

import importlib.util
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "review", ROOT / "plugins/asta-tools/skills/workspace/assets/deck-review.py"
)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
THEMED_JS = (
    "() => ['bootstrap', 'asta-theme'].every(name => [...document.styleSheets]"
    ".some(s => s.href && s.href.includes(name) && s.cssRules.length))"
)


def check_site(site, artifacts):
    """Shared acceptance contract for local reports and the published demo."""
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
    server = review._serve(str(site))
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/what-changed.html")
            if not page.evaluate(THEMED_JS):
                missing.append("the site's theme")
            if page.locator(".deck-review").count():
                page.locator(".deck-review").wait_for()
                if page.locator(".dr-changed, .dr-new, .dr-look").count() == 0:
                    missing.append("the changed slide")
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
    parser.add_argument("project", type=Path)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument(
        "--site", action="store_true", help="Check an already-built report"
    )
    args = parser.parse_args()
    project = args.project.resolve()
    if args.site:
        site = project
    else:
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
