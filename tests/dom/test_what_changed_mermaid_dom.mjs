import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { DOMParser, parseHTML } from "linkedom";

// The script that draws What changed's Mermaid diagrams, as the generated page
// carries it, run here against a stand-in Mermaid (a real one needs a browser's
// layout). What it must do: configure strict mode with no auto-start, draw only the
// old/new pairs, scrub what Mermaid returns, and leave the text when drawing fails.

const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), "what-changed-mermaid-"));
const MERMAID = "site_libs/quarto-diagram/mermaid.min.js";

function site(root, label) {
  fs.mkdirSync(path.join(root, path.dirname(MERMAID)), { recursive: true });
  fs.writeFileSync(path.join(root, MERMAID), "globalThis.mermaid = {};");
  fs.writeFileSync(
    path.join(root, "p.html"),
    `<html><head><script src="${MERMAID}"></script></head><body><main><p>Same.</p>` +
      `<div><pre class="mermaid mermaid-js">flowchart LR\n  A --&gt; ${label}\n</pre></div>` +
      "</main></body></html>",
  );
}
const oldRoot = path.join(fixtureRoot, "old");
const newRoot = path.join(fixtureRoot, "new");
site(oldRoot, "B");
site(newRoot, "C");
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

const drawing = page.match(/<script>(\s*\(function \(\) \{\s*"use strict";\s*var mermaid = window\.mermaid;[\s\S]*?)<\/script>/);
assert.ok(drawing, "the page must carry the Mermaid drawing script");
const pinned = page.match(/<script src="(https:\/\/cdn\.jsdelivr\.net\/npm\/mermaid@11\.12\.0\/[^"]*)" integrity="(sha384-[^"]+)" crossorigin="anonymous"><\/script>/);
assert.ok(pinned, "and the pinned Mermaid, with its integrity hash");
assert.ok(!page.includes(MERMAID), "never the site's own copy");
const body = page.slice(page.indexOf("<body"), page.indexOf("<script>"));

const HOSTILE_SVG =
  '<svg id="wc-mermaid-0" viewBox="0 0 10 10" onload="alert(1)">' +
  "<style>#wc-mermaid-0 .node{fill:#eee}</style>" +
  "<script>alert(2)</script>" +
  '<a xlink:href="javascript:alert(3)" href="https://evil.example/"><text>go</text></a>' +
  '<image href="data:image/svg+xml;base64,AAAA"/>' +
  '<use href="#shape"/>' +
  '<animate attributeName="href" values="javascript:alert(4)"/>' +
  '<foreignObject><div onclick="alert(5)"><span class="nodeLabel">label text</span>' +
  '<img src="x" onerror="alert(6)"><iframe src="https://evil.example/"></iframe>' +
  "</div></foreignObject></svg>";

function run({ render, withMermaid = true, mode = null, loaded = false, autoLoad = true, before = null }) {
  const { document, window } = parseHTML(`<!doctype html><html><body>${body}
    <pre class="mermaid" id="outside">flowchart LR\n  X --&gt; Y</pre></body></html>`);
  if (mode) document.documentElement.setAttribute("data-wc-mode", mode);
  const calls = { initialize: [], render: [] };
  if (withMermaid) {
    window.mermaid = {
      initialize: (config) => calls.initialize.push(JSON.parse(JSON.stringify(config))),
      render: (id, text) => {
        calls.render.push({ id, text });
        return render(id, text);
      },
      run: () => assert.fail("mermaid.run draws every diagram of the page"),
      contentLoaded: () => assert.fail("nothing is drawn on load"),
    };
  }
  window.matchMedia = () => ({ matches: false });
  if (before) before(window, document);
  // A page still loading: nothing is drawn until its load event.
  Object.defineProperty(document, "readyState", { value: loaded ? "complete" : "loading" });
  new Function("window", "document", "DOMParser", drawing[1])(window, document, DOMParser);
  const fire = () => window.dispatchEvent(new window.Event("load"));
  if (!loaded && autoLoad) fire();
  const settled = new Promise((resolve) => setTimeout(resolve, 20));
  return { document, window, calls, settled, fire };
}

test("it configures Mermaid strict with no auto-start, before drawing anything", async () => {
  const { document, calls, settled } = run({ render: (id) => Promise.resolve({ svg: `<svg id="${id}"></svg>` }) });
  await settled;
  assert.equal(calls.initialize.length, 1);
  const config = calls.initialize[0];
  assert.equal(config.securityLevel, "strict");
  assert.equal(config.startOnLoad, false);
  assert.ok(config.secure.includes("securityLevel") && config.secure.includes("themeCSS"));
  assert.equal(config.theme, "default");
  assert.ok(document.querySelector("pre[data-wc-drawn] svg"));
});

test("it draws only the old and new of a changed diagram, from their text", async () => {
  const { document, calls, settled } = run({ render: (id) => Promise.resolve({ svg: `<svg id="${id}"></svg>` }) });
  await settled;
  assert.equal(calls.render.length, 2);
  assert.match(calls.render[0].text, /A --> B/);
  assert.match(calls.render[1].text, /A --> C/);
  assert.equal(document.querySelectorAll("del.wc-unit > pre[data-wc-drawn], ins.wc-unit > pre[data-wc-drawn]").length, 2);
  // a diagram outside an old/new pair is not drawn
  assert.equal(document.getElementById("outside").hasAttribute("data-wc-drawn"), false);
  assert.match(document.getElementById("outside").textContent, /X --> Y/);
});

test("it waits for the page to load before it draws, and draws at once when it has", async () => {
  const draw = (id) => Promise.resolve({ svg: `<svg id="${id}"></svg>` });
  const loading = run({ render: draw, autoLoad: false });
  await loading.settled;
  assert.equal(loading.calls.render.length, 0, "nothing is drawn while the page loads");
  loading.fire();
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(loading.calls.render.length, 2);
  const done = run({ render: draw, loaded: true });
  await done.settled;
  assert.equal(done.calls.render.length, 2, "a loaded page is drawn without a load event");
});

test("it draws on a dark page with Mermaid's dark theme", async () => {
  const { calls, settled } = run({ render: (id) => Promise.resolve({ svg: `<svg id="${id}"></svg>` }), mode: "dark" });
  await settled;
  assert.equal(calls.initialize[0].theme, "dark");
});

test("what Mermaid returns is scrubbed: no script, handler, link or outside reference", async () => {
  const { document, settled } = run({ render: () => Promise.resolve({ svg: HOSTILE_SVG }) });
  await settled;
  const drawn = document.querySelector("ins.wc-unit > pre[data-wc-drawn]");
  assert.ok(drawn, "the diagram is drawn");
  const markup = drawn.innerHTML;
  assert.ok(!/<script|<iframe|<animate/i.test(markup), markup);
  assert.ok(!/\son[a-z]+\s*=/i.test(markup), markup);
  assert.ok(!/javascript:|evil\.example|data:/i.test(markup), markup);
  // the drawing itself stays: its style, its label text, a reference inside it
  assert.ok(drawn.querySelector("style"));
  assert.match(drawn.textContent, /go/);
  assert.match(drawn.textContent, /label text/);
  assert.equal(drawn.querySelector("use").getAttribute("href"), "#shape");
});

test("a diagram Mermaid cannot draw stays as its text, and leaves nothing behind", async () => {
  const { document, calls, settled } = run({
    render: (id) => {
      const stray = document.createElement("div");
      stray.id = `d${id}`;
      document.body.appendChild(stray);
      return Promise.reject(new Error("Parse error"));
    },
  });
  await settled;
  assert.equal(calls.render.length, 2, "each diagram has its own failure");
  assert.equal(document.querySelectorAll("[data-wc-drawn]").length, 0);
  assert.match(document.querySelector("ins.wc-unit > pre").textContent, /A --> C/);
  assert.equal(document.querySelector('[id^="dwc-mermaid"]'), null);
  // and a render that throws, or returns no drawing, is no different
  const thrown = run({ render: () => { throw new Error("boom"); } });
  await thrown.settled;
  assert.equal(thrown.document.querySelectorAll("[data-wc-drawn]").length, 0);
  const empty = run({ render: () => Promise.resolve({ svg: "<p>not a drawing</p>" }) });
  await empty.settled;
  assert.equal(empty.document.querySelectorAll("[data-wc-drawn]").length, 0);
});

test("with no Mermaid loaded the text stays", async () => {
  const { document, settled } = run({ render: () => assert.fail("no Mermaid"), withMermaid: false });
  await settled;
  assert.equal(document.querySelectorAll("[data-wc-drawn]").length, 0);
  assert.match(document.querySelector("del.wc-unit > pre").textContent, /A --> B/);
});

test("once the diagrams are drawn it asks the page to lay its pairs out again", async () => {
  const draw = (id) => Promise.resolve({ svg: `<svg id="${id}"></svg>` });
  const seen = [];
  const { document, settled } = run({
    render: draw,
    before: (window, document) => {
      window.wcPairLayout = () =>
        seen.push(document.querySelectorAll("pre[data-wc-drawn]").length);
    },
  });
  await settled;
  assert.deepEqual(seen, [2], "once, after both are drawn");
  assert.ok(document.querySelector("pre[data-wc-drawn]"));
  // with no layout script on the page, drawing is no different
  const alone = run({ render: draw });
  await alone.settled;
  assert.equal(alone.document.querySelectorAll("pre[data-wc-drawn]").length, 2);
});

test("the page's views have their diagrams drawn the same way, inside the view only", async () => {
  const { document, window, calls, settled } = run({
    render: (id) => Promise.resolve({ svg: `<svg id="${id}"></svg>` }),
    loaded: true,
  });
  await settled;
  assert.equal(calls.render.length, 2);
  const view = document.createElement("div");
  view.innerHTML = '<pre class="mermaid mermaid-js">flowchart LR\n  A --&gt; Z</pre><pre>not a diagram</pre>';
  document.body.appendChild(view);
  assert.equal(typeof window.wcMermaid, "function");
  window.wcMermaid(view);
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(calls.render.length, 3);
  assert.match(calls.render[2].text, /A --> Z/);
  assert.notEqual(calls.render[2].id, calls.render[0].id, "each drawing has an id of its own");
  assert.notEqual(calls.render[2].id, calls.render[1].id);
  assert.ok(view.querySelector("pre.mermaid[data-wc-drawn] svg"));
  assert.equal(view.querySelectorAll("[data-wc-drawn]").length, 1);
  assert.equal(document.getElementById("outside").hasAttribute("data-wc-drawn"), false);
});

// A page whose prose changed and whose diagram did not: no old/new pair holds it, yet
// Clean and Before / after must show it drawn, as they do on a page where it changed.
const quiet = fs.mkdtempSync(path.join(os.tmpdir(), "what-changed-mermaid-quiet-"));
function quietSite(root, sentence) {
  fs.mkdirSync(path.join(root, path.dirname(MERMAID)), { recursive: true });
  fs.writeFileSync(path.join(root, MERMAID), "globalThis.mermaid = {};");
  fs.writeFileSync(
    path.join(root, "p.html"),
    `<html><head><script src="${MERMAID}"></script></head><body><main><p>${sentence}</p>` +
      '<div><pre class="mermaid mermaid-js">flowchart LR\n  A --&gt; B\n</pre></div>' +
      "</main></body></html>",
  );
}
quietSite(path.join(quiet, "old"), "Tea is good.");
quietSite(path.join(quiet, "new"), "Tea is great.");
const quietOut = path.join(quiet, "what-changed.html");
const quietRun = spawnSync(
  "python3",
  [
    "plugins/asta-tools/skills/workspace/assets/what-changed.py",
    "--old", path.join(quiet, "old"), "--new", path.join(quiet, "new"), "--out", quietOut,
  ],
  { cwd: repoRoot, encoding: "utf8" },
);
assert.equal(quietRun.status, 0, quietRun.stderr);
const quietPage = fs.readFileSync(quietOut, "utf8");
fs.rmSync(quiet, { recursive: true, force: true });
const quietScripts = [...quietPage.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const quietDrawing = quietScripts.find((s) => s.includes("var mermaid = window.mermaid;"));
const quietViews = quietScripts.find((s) => s.includes("wcView") && s.includes("wc-views"));

test("an unchanged diagram is drawn in Clean and in Before / after, though no pair holds it", async () => {
  assert.ok(quietDrawing, "the page carries the drawing script, for the views");
  assert.ok(quietViews, "and the script that sets the views");
  assert.ok(!/<(?:del|ins) class="wc-unit"><pre class="mermaid/.test(quietPage), "no pair holds the diagram");
  const { document, window } = parseHTML(quietPage);
  const calls = { initialize: 0, render: [] };
  // linkedom's windows share a prototype: what an earlier test's script defined there
  // would stand in for the hook this page's script must define itself.
  delete Object.getPrototypeOf(window).wcMermaid;
  delete window.wcMermaid;
  window.mermaid = {
    initialize: () => { calls.initialize++; },
    render: (id, text) => {
      calls.render.push(text);
      return Promise.resolve({ svg: `<svg id="${id}"></svg>` });
    },
  };
  window.matchMedia = () => ({ matches: false });
  window.scrollBy = () => {};
  Object.defineProperty(document, "readyState", { value: "complete" });
  new Function("window", "document", "DOMParser", quietDrawing)(window, document, DOMParser);
  assert.equal(typeof window.wcMermaid, "function");
  Function("document", "window", quietViews)(document, window);
  const section = document.querySelector("section.page-diff");
  for (const [view, box] of [["clean", ".wc-clean"], ["before", ".wc-ba"]]) {
    section.querySelector(`.wc-head [data-wc-view="${view}"]`).click();
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.ok(section.querySelector(`${box} pre.mermaid[data-wc-drawn] svg`), `${view} draws the diagram`);
    assert.equal(section.querySelector(`${box} pre.mermaid:not([data-wc-drawn])`), null, `${view} leaves none as text`);
  }
  assert.ok(calls.initialize >= 1);
  assert.ok(calls.render.every((t) => /A --> B/.test(t)));
  // and the page's changed-marks view still has no diagram to draw
  assert.equal(document.querySelectorAll("del.wc-unit > pre, ins.wc-unit > pre").length, 0);
});
