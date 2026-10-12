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

async function runViewer({ pdf = false, reject = false } = {}) {
  const { document, window } = parseHTML(`<html><body>${raw}</body></html>`);
  Object.defineProperty(document, "baseURI", { value: "https://preview.example/project/paper/html/index.html" });
  assert.equal(document.querySelectorAll("a[href], iframe[src]").length, 0,
    "render-time link checkers must not encounter unpublished artifacts");
  const requests = [];
  const fetch = async (url, options) => {
    requests.push([url, options.method]);
    if (reject) throw new Error("offline");
    return { ok: pdf };
  };
  vm.runInNewContext(code, { document, fetch, URL, location: { origin: "https://preview.example" } });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(requests, [["../../paper-previews/paper/main.pdf", "HEAD"]]);
  return { document, window };
}

test("missing or unreachable PDF retains the explanation without broken links", async () => {
  for (const options of [{}, { reject: true }]) {
    const { document } = await runViewer(options);
    assert.equal(document.querySelectorAll("a, iframe").length, 0);
    assert.match(document.body.textContent, /PDF appears after the preview build/);
  }
});

test("available PDF is linked and embedded", async () => {
  const { document } = await runViewer({ pdf: true });
  const links = document.querySelectorAll("[data-paper-links] a");
  assert.equal(links.length, 1);
  assert.equal(links[0].getAttribute("href"), "../../paper-previews/paper/main.pdf");
  const frame = document.querySelector("iframe");
  assert.equal(frame.getAttribute("src"), "../../paper-previews/paper/main.pdf");
  assert.equal(frame.getAttribute("title"), "Paper");
});
