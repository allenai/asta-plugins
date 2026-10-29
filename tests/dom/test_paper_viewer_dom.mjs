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
const base = "../../paper-previews/paper/";

async function runViewer({ files = [], reject = false, stored = {}, contents = {} } = {}) {
  const { document, window } = parseHTML(`<html><body>${raw}</body></html>`);
  Object.defineProperty(document, "baseURI", { value: "https://preview.example/project/paper/html/index.html" });
  assert.equal(document.querySelectorAll("a[href], iframe[src]").length, 0,
    "render-time link checkers must not encounter unpublished artifacts");
  window.HTMLElement.prototype.getBoundingClientRect ??= () => ({ top: 80, bottom: 800, height: 720 });
  const requests = [];
  const fetch = async (url, options) => {
    requests.push([url, options.method]);
    if (reject) throw new Error("offline");
    const file = files.find(name => url === base + name);
    return { ok: file !== undefined, text: async () => contents[file] ?? "" };
  };
  const listeners = {};
  const storage = { ...stored };
  vm.runInNewContext(code, {
    document,
    fetch,
    URL,
    location: { origin: "https://preview.example" },
    innerHeight: 800,
    scrollY: 0,
    addEventListener: (type, listener) => (listeners[type] ??= []).push(listener),
    localStorage: { getItem: key => storage[key] ?? null, setItem: (key, value) => { storage[key] = value; } },
    ResizeObserver: class { observe() {} },
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(requests, [
    [base + "build-failed.txt", "HEAD"], [base + "latex-errors.json", "GET"],
    [base + "main.pdf", "HEAD"], [base + "what-changed.pdf", "HEAD"],
  ]);
  const press = key => (listeners.keydown ?? []).forEach(listener => listener({ key }));
  return { document, window, storage, press };
}

test("missing or unreachable PDF retains the explanation without broken links", async () => {
  for (const options of [{}, { reject: true }]) {
    const { document } = await runViewer(options);
    assert.equal(document.querySelectorAll("a, iframe, object").length, 0);
    assert.match(document.body.textContent, /PDF appears after the preview build/);
  }
});

test("available PDF is embedded without its thumbnail pane, with a link only as the fallback", async () => {
  const { document } = await runViewer({ files: ["main.pdf"] });
  const frame = document.querySelector("[data-paper-pdf] object");
  assert.equal(frame.getAttribute("data"), base + "main.pdf#navpanes=0&view=FitH");
  assert.equal(frame.getAttribute("type"), "application/pdf");
  assert.equal(frame.getAttribute("title"), "Paper");
  // Without a marked PDF (the main site), there's nothing to switch to.
  assert.equal(document.querySelector(".paper-modes").hidden, true);
  // The link sits inside the object, so a browser shows it only when it
  // can't display the PDF inline.
  const links = document.querySelectorAll("a");
  assert.equal(links.length, 1);
  assert.equal(links[0].parentElement, frame);
  assert.equal(links[0].getAttribute("href"), base + "main.pdf");
});

test("a pull request's preview opens on its changes marked, with a switch to the clean paper", async () => {
  const { document } = await runViewer({ files: ["main.pdf", "what-changed.pdf"] });
  const data = () => document.querySelector("[data-paper-pdf] object").getAttribute("data");
  const pressed = () => [...document.querySelectorAll(".paper-modes button")]
    .map(button => [button.dataset.file, button.getAttribute("aria-pressed")]);
  assert.equal(document.querySelector(".paper-modes").hidden, false);
  assert.equal(data(), base + "what-changed.pdf#navpanes=0&view=FitH");
  assert.deepEqual(pressed(), [["what-changed.pdf", "true"], ["main.pdf", "false"]]);
  document.querySelector('.paper-modes [data-file="main.pdf"]').click();
  assert.equal(data(), base + "main.pdf#navpanes=0&view=FitH");
  assert.deepEqual(pressed(), [["what-changed.pdf", "false"], ["main.pdf", "true"]]);
});

test("the expand button gives the paper the whole window, and Esc gives the site back", async () => {
  const { document, storage, press } = await runViewer({ files: ["main.pdf"] });
  const host = document.querySelector("[data-paper-preview]");
  const expand = document.querySelector(".paper-expand");
  expand.click();
  assert.equal(host.classList.contains("paper-full"), true);
  assert.equal(document.body.classList.contains("paper-page-full"), true);
  assert.equal(expand.getAttribute("aria-pressed"), "true");
  assert.equal(storage["paper-page-full"], "1");
  press("Escape");
  assert.equal(host.classList.contains("paper-full"), false);
  assert.equal(document.body.classList.contains("paper-page-full"), false);
  assert.equal(storage["paper-page-full"], "");
});

test("the whole-window choice is kept for the next page load", async () => {
  const { document } = await runViewer({ files: ["main.pdf"], stored: { "paper-page-full": "1" } });
  assert.equal(document.querySelector("[data-paper-preview]").classList.contains("paper-full"), true);
});

test("errors the paper built past show beside the PDF with the log", async () => {
  const { document } = await runViewer({
    files: ["main.pdf", "latex-errors.json"],
    contents: { "latex-errors.json": '{"errors":2,"warnings":1}' },
  });
  const issues = document.querySelector(".paper-issues");
  assert.equal(issues.hidden, false);
  assert.match(issues.textContent, /2 LaTeX errors and 1 warning \(unresolved citations or a missing bibliography\)/);
  assert.equal(issues.querySelector("a").getAttribute("href"), base + "main.log");
});

test("a failed latest build says so beside the last good PDF", async () => {
  const { document } = await runViewer({ files: ["main.pdf", "build-failed.txt"] });
  const issues = document.querySelector(".paper-issues");
  assert.match(issues.textContent, /latest version did not build/);
  assert.equal(issues.querySelector("a").getAttribute("href"), base + "build-failed.txt");
  assert.ok(document.querySelector("[data-paper-pdf] object"));
});

test("a compiler failure with no counted LaTeX errors shows its exit status", async () => {
  const { document } = await runViewer({
    files: ["main.pdf", "latex-errors.json"],
    contents: { "latex-errors.json": '{"errors":0,"warnings":0,"latexmk_exit_status":12}' },
  });
  const issues = document.querySelector(".paper-issues");
  assert.equal(issues.hidden, false);
  assert.match(issues.textContent, /a compiler failure \(exit status 12\)/);
  assert.doesNotMatch(issues.textContent, /LaTeX errors/);
  assert.equal(issues.querySelector("a").getAttribute("href"), base + "main.log");
  assert.ok(document.querySelector("[data-paper-pdf] object"));
});

test("a clean build shows no issues note", async () => {
  const { document } = await runViewer({ files: ["main.pdf"] });
  assert.equal(document.querySelector(".paper-issues").hidden, true);
});
