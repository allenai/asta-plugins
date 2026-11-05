// Inspect the files actually published to gh-pages while Pages awaits its switch.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { createInterface } from "node:readline";
import { chromium } from "playwright";

// This acceptance check follows the example's attention deck; update together
// with the example if its deck location or overview label changes.
const exampleDeck = {
  viewer: "slides/attention/index.html",
  overviewLabel: "Presentation slides",
};
const site = resolve(process.argv[2]);
const output = resolve(process.argv[3]);
assert.match(process.env.PR_NUMBER ?? "", /^[1-9][0-9]*$/, "PR_NUMBER is required");
const previewPath = `/pr-preview/pr-${process.env.PR_NUMBER}/`;
function requirePreviewLink(href, base) {
  assert.ok(href.startsWith(base), `link stays in the preview: ${href}`);
}
await mkdir(output, { recursive: true });
const server = spawn("python3", ["-u", "-c", `
import functools, http.server, sys
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=sys.argv[1])
with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
    print(server.server_port, flush=True)
    server.serve_forever()
`, site], { stdio: ["ignore", "pipe", "inherit"] });
let browser;
try {
  const lines = createInterface({ input: server.stdout });
  const port = await new Promise((done, fail) => {
    const cleanup = () => {
      server.off("error", error);
      server.off("exit", exit);
      lines.close();
    };
    const error = err => { cleanup(); fail(err); };
    const exit = code => error(new Error(`server exited: ${code}`));
    lines.once("line", port => { cleanup(); done(port); });
    server.once("error", error);
    server.once("exit", exit);
  });
  const base = `http://127.0.0.1:${port}${previewPath}`;
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  for (const [path, screenshot] of [
    ["index.html", "example-preview-home.png"],
    ["what-changed.html", "example-preview-what-changed.png"],
    [exampleDeck.viewer, "example-preview-deck-viewer.png"],
  ]) {
    const response = await page.goto(`${base}${path}`, { waitUntil: "domcontentloaded" });
    assert.equal(response.status(), 200, path);
    requirePreviewLink(page.url(), base);
    // A root-relative link must fail even when the same file exists at root.
    const escaped = await page.evaluate(() => new URL("/slides/attention/slides.html", location.href).href);
    assert.throws(() => requirePreviewLink(escaped, base), /link stays in the preview/);
    if (path === "what-changed.html") {
      assert.match(await page.locator("body").innerText(), /What changed/i);
      const changedSlides = page.locator("article.slide-diff:not(.removed)");
      const slideLinks = changedSlides.locator("h3 a");
      assert.equal(await slideLinks.count(), await changedSlides.count(),
        "every new or changed slide has a preview link");
      // A home/theme-only edit may correctly have no changed slides. When the
      // diff lists slides, each must link into these pushed files, never live.
      for (const href of await slideLinks.evaluateAll(links => links.map(link => link.href))) {
        requirePreviewLink(href, base);
        assert.equal((await page.request.get(href)).status(), 200, "changed slide link");
      }
    } else if (path === "index.html") {
      const link = page.getByRole("link", { name: exampleDeck.overviewLabel, exact: true });
      await link.waitFor();
      requirePreviewLink(await link.evaluate(el => el.href), base);
    } else {
      requirePreviewLink(await page.locator("iframe").evaluate(el => el.src), base);
      const frame = page.frameLocator("iframe");
      await frame.locator(".reveal .slides section.present").first().waitFor();
      assert.ok(await page.locator("#quarto-sidebar").isVisible());
    }
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: resolve(output, screenshot), fullPage: true });
  }
} finally {
  await browser?.close();
  server.kill();
}
