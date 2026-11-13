import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseHTML } from "linkedom";

// The script that sets a changed figure's old and new side by side or, when the
// figure is wider than half the column at its natural size, old above new. The
// script is the generated page's own; widths are stood in (a real layout needs a
// browser), the room of one unit being set per test.

const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), "what-changed-pairs-"));
function site(root, bytes) {
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(path.join(root, "plot.png"), bytes);
  fs.writeFileSync(
    path.join(root, "p.html"),
    '<html><body><main><p>Same.</p><p><img src="plot.png" alt="Plot"></p></main></body></html>',
  );
}
const oldRoot = path.join(fixtureRoot, "old");
const newRoot = path.join(fixtureRoot, "new");
site(oldRoot, "old bytes");
site(newRoot, "new bytes");
const outputPath = path.join(fixtureRoot, "what-changed.html");
const generated = spawnSync(
  "python3",
  [
    "plugins/asta-tools/skills/workspace/assets/what-changed.py",
    "--old",
    oldRoot,
    "--new",
    newRoot,
    "--out",
    outputPath,
  ],
  { cwd: repoRoot, encoding: "utf8" },
);
assert.equal(generated.status, 0, generated.stderr);
const page = fs.readFileSync(outputPath, "utf8");
fs.rmSync(fixtureRoot, { recursive: true, force: true });
const layout = page.match(/<script>(\s*\(function \(\) \{\s*"use strict";\s*var STACK[\s\S]*?)<\/script>/);
assert.ok(layout, "a page with a changed figure carries the pair layout script");
assert.equal(page.split("var STACK").length - 1, 1, "once");

const mermaidSvg = (max) =>
  `<svg width="100%" viewBox="0 0 ${max} 80" style="max-width: ${max}px;" role="graphics-document"></svg>`;
const pair = (inner, extra = "") =>
  `<div class="pair">${inner.replace("%", "del")}${inner.replace("%", "ins")}${extra}</div>`;
const unit = (tag, figure) => `<${tag} class="wc-unit">${figure}</${tag}>`;
const figs = (figure) => `<div class="pair">${unit("del", figure)}${unit("ins", figure)}</div>`;

// `room` is what one unit has side by side: its client width less its padding.
function run(html, { room = 400, pad = 8 } = {}) {
  const { document, window } = parseHTML(`<!doctype html><html><body>${html}</body></html>`);
  const state = { room };
  window.getComputedStyle = () => ({ paddingLeft: `${pad}px`, paddingRight: `${pad}px` });
  for (const u of document.querySelectorAll(".wc-unit")) {
    Object.defineProperty(u, "clientWidth", { get: () => state.room + 2 * pad });
  }
  Object.defineProperty(document, "readyState", { value: "loading" });
  new Function("window", "document", layout[1])(window, document);
  window.dispatchEvent(new window.Event("load"));
  return { document, window, state };
}
const stacked = (document, i = 0) =>
  document.querySelectorAll(".pair")[i].classList.contains("wc-pair-stack");

test("a drawn Mermaid pair wider than half the column is old above new at its natural size", () => {
  const drawn = (max) => `<pre class="mermaid" data-wc-drawn="">${mermaidSvg(max)}</pre>`;
  const { document } = run(figs(drawn(800)), { room: 380 });
  assert.ok(stacked(document));
  for (const svg of document.querySelectorAll("svg")) {
    assert.equal(svg.style.width, "min(800px, 100%)");
  }
});

test("a narrow Mermaid pair stays side by side", () => {
  const { document } = run(figs(`<pre class="mermaid" data-wc-drawn="">${mermaidSvg(300)}</pre>`), { room: 380 });
  assert.ok(!stacked(document));
  assert.equal(document.querySelector("svg").style.width, "");
});

test("a pair the old is narrow and the new is wide stacks, each at its own width", () => {
  const html = `<div class="pair">${unit("del", mermaidSvg(200))}${unit("ins", mermaidSvg(900))}</div>`;
  const { document } = run(html, { room: 380 });
  assert.ok(stacked(document));
  const [del, ins] = document.querySelectorAll("svg");
  assert.equal(del.style.width, "min(200px, 100%)");
  assert.equal(ins.style.width, "min(900px, 100%)");
});

test("an image pair follows its natural width: its width attribute, else its file's", () => {
  const wide = run(figs('<img src="a.png" width="700" alt="">'), { room: 380 });
  assert.ok(stacked(wide.document));
  assert.equal(wide.document.querySelector("img").style.width, "min(700px, 100%)");
  const small = run(figs('<img src="a.png" width="200" alt="">'), { room: 380 });
  assert.ok(!stacked(small.document));
  // no width attribute: the file's own width, once it is known
  const sized = (naturalWidth) => {
    const { document, window, state } = run(figs('<img src="a.png" alt="">'), { room: 380 });
    for (const img of document.querySelectorAll("img")) img.naturalWidth = naturalWidth;
    window.wcPairLayout();
    return { document, state, window };
  };
  assert.ok(stacked(sized(900).document));
  assert.ok(!stacked(sized(250).document));
  // an image with no size known (not loaded) is left side by side
  const unknown = run(figs('<img src="a.png" alt="">'), { room: 380 });
  assert.ok(!stacked(unknown.document));
});

test("the same rule at 390px: what is wider than half that column stacks", () => {
  // a 390px page: 16px gutters, a 16px gap, two units of (390 - 32 - 16) / 2, less padding
  const room = (390 - 32 - 16) / 2 - 16;
  const img = (w) => figs(`<img src="a.png" width="${w}" alt="">`);
  assert.ok(stacked(run(img(room + 20), { room }).document));
  assert.ok(!stacked(run(img(room - 20), { room }).document));
});

test("a pair is laid out again on resize, and goes back to side by side when it fits", async () => {
  const { document, window, state } = run(figs('<img src="a.png" width="500" alt="">'), { room: 380 });
  assert.ok(stacked(document));
  state.room = 700;
  window.dispatchEvent(new window.Event("resize"));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.ok(!stacked(document));
  assert.equal(document.querySelector("img").style.width, "");
});

test("a diagram not drawn yet is left alone, and laid out when it is", () => {
  const { document, window } = run(
    figs('<pre class="mermaid">flowchart LR\n  A --&gt; B</pre>'),
    { room: 380 },
  );
  assert.ok(!stacked(document));
  for (const pre of document.querySelectorAll("pre")) {
    pre.setAttribute("data-wc-drawn", "");
    pre.innerHTML = mermaidSvg(800);
  }
  window.wcPairLayout();
  assert.ok(stacked(document));
});

test("a parent that holds more than the pair is not a pair", () => {
  const html = `<div class="pair">${unit("del", mermaidSvg(900))}${unit("ins", mermaidSvg(900))}<span>text</span></div>`;
  const { document } = run(html, { room: 380 });
  assert.ok(!stacked(document));
});
