// Inspect the files actually published to gh-pages while Pages awaits its switch.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { createInterface } from "node:readline";
import { chromium } from "playwright";

const site = resolve(process.argv[2]);
const output = resolve(process.argv[3]);
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
  const base = `http://127.0.0.1:${port}`;
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  for (const [path, screenshot] of [
    ["index.html", "example-preview-home.png"],
    ["what-changed.html", "example-preview-what-changed.png"],
    ["slides/attention/index.html", "example-preview-deck-viewer.png"],
  ]) {
    const response = await page.goto(`${base}/${path}`, { waitUntil: "domcontentloaded" });
    assert.equal(response.status(), 200, path);
    if (path === "what-changed.html") {
      assert.match(await page.locator("body").innerText(), /What changed/i);
      for (const href of await page.locator('a[href*="slides/attention/slides.html"]').evaluateAll(
        links => links.map(link => link.href),
      )) {
        assert.equal((await page.request.get(href)).status(), 200, "changed slide link");
      }
    } else if (path === "index.html") {
      await page.getByRole("link", { name: "Presentation slides", exact: true }).waitFor();
    } else {
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
