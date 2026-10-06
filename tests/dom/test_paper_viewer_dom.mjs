import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

import { parseHTML } from "linkedom";

const root = fs.mkdtempSync(path.join(os.tmpdir(), "paper-viewer-dom-"));
const script = fileURLToPath(new URL("../../plugins/asta-tools/skills/workspace/assets/paper-viewer.py", import.meta.url));
const generated = spawnSync("python3", [script], {
  cwd: root,
  input: JSON.stringify({ papers: ["paper"] }),
  encoding: "utf8",
});
assert.equal(generated.status, 0, generated.stderr);
const page = fs.readFileSync(path.join(root, "paper/html/index.qmd"), "utf8");
fs.rmSync(root, { recursive: true, force: true });
const raw = page.match(/```\{=html\}\n([\s\S]*?)\n```/)[1];
const code = raw.match(/<script>([\s\S]*?)<\/script>/)[1];

async function runViewer({ pdf = false, html = false, reject = false } = {}) {
  const { document, window } = parseHTML(`<html><body>${raw}</body></html>`);
  Object.defineProperty(document, "baseURI", { value: "https://preview.example/project/paper/html/index.html" });
  assert.equal(document.querySelectorAll("a[href], iframe[src]").length, 0,
    "render-time link checkers must not encounter unpublished artifacts");
  const requests = [];
  const fetch = async (url, options) => {
    requests.push([url, options.method]);
    if (reject) throw new Error("offline");
    return { ok: url.endsWith(".pdf") ? pdf : html };
  };
  vm.runInNewContext(code, { document, fetch, URL, location: { origin: "https://preview.example" } });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(requests, [
    ["../../paper-previews/paper/main.pdf", "HEAD"],
    ["../../paper-previews/paper/html/index.html", "HEAD"],
  ]);
  return { document, window };
}

test("failed HTML conversion still exposes a working PDF", async () => {
  const { document } = await runViewer({ pdf: true });
  const links = document.querySelectorAll("a");
  assert.equal(links.length, 1);
  assert.equal(links[0].getAttribute("href"), "../../paper-previews/paper/main.pdf");
  assert.equal(document.querySelector("iframe"), null);
  assert.match(document.body.textContent, /use the PDF link when available/);
});

test("missing or unreachable artifacts retain the explanation without broken links", async () => {
  for (const options of [{}, { reject: true }]) {
    const { document } = await runViewer(options);
    assert.equal(document.querySelectorAll("a, iframe").length, 0);
    assert.match(document.body.textContent, /artifacts appear after the preview build/);
  }
});

test("available HTML embeds safely and external references open outside the frame", async () => {
  const { document, window } = await runViewer({ pdf: true, html: true });
  assert.equal(document.querySelectorAll("[data-paper-links] a").length, 2);
  const frame = document.querySelector("iframe");
  assert.equal(frame.getAttribute("src"), "../../paper-previews/paper/html/index.html");
  assert.equal(frame.getAttribute("sandbox"), "allow-same-origin allow-popups allow-popups-to-escape-sandbox");
  const paper = parseHTML(`<html><body>
    <a href="https://[invalid">Malformed link</a>
    <a id="external" href="https://doi.org/10.1234/example">DOI</a>
    <a id="internal" href="#references">References</a>
  </body></html>`).document;
  Object.defineProperty(frame, "contentDocument", { value: paper });
  frame.dispatchEvent(new window.Event("load"));
  assert.equal(paper.querySelector("#external").target, "_blank");
  assert.equal(paper.querySelector("#external").rel, "noopener noreferrer");
  assert.notEqual(paper.querySelector("#internal").target, "_blank");
});
