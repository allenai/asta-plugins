import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseHTML } from "linkedom";

const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), "what-changed-paper-dom-"));
const oldRoot = path.join(fixtureRoot, "old");
const newRoot = path.join(fixtureRoot, "new");
const outputPath = path.join(fixtureRoot, "what-changed.html");
fs.mkdirSync(oldRoot);
fs.mkdirSync(path.join(newRoot, "paper-previews/paper"), { recursive: true });
fs.writeFileSync(
  path.join(newRoot, "paper-previews/paper/preview.json"),
  JSON.stringify({ changed: true, diff: true }),
);
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
const generatedPage = fs.readFileSync(outputPath, "utf8");
fs.rmSync(fixtureRoot, { recursive: true, force: true });
const paperScript = [...generatedPage.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(match => match[1])
  .find(source => source.includes(".paper-view"));
assert.ok(paperScript, "generated page must contain the paper viewer's script");

// A page the script can run in: linkedom has no layout or scrolling, so the
// window's scroll position, the section's place, the animation frame and the
// timers are stand-ins the tests drive.
function report() {
  const { document, window } = parseHTML(generatedPage);
  const section = document.querySelector("section.page-diff");
  const env = {
    sectionTop: 1000, // the section's place in the page, which the page's own height decides
    scrollY: 1200,
    scrolls: [],
    frames: [],
    timers: [],
    focused: [],
  };
  section.getBoundingClientRect = () => ({ top: env.sectionTop - env.scrollY });
  window.HTMLElement.prototype.focus = function (options) { env.focused.push([this, options]); };
  const win = {
    get scrollY() { return env.scrollY; },
    scrollTo: (x, y) => { env.scrolls.push(y); env.scrollY = y; },
  };
  Function("document", "window", "requestAnimationFrame", "setTimeout", paperScript)(
    document, win, callback => env.frames.push(callback), (callback, ms) => env.timers.push([ms, callback]),
  );
  const press = key => {
    const event = new window.Event("keydown");
    event.key = key;
    document.dispatchEvent(event);
  };
  // Let the animation frame and every timer run, in order of delay.
  const settle = () => {
    env.frames.splice(0).forEach(callback => callback());
    env.timers.sort((a, b) => a[0] - b[0]).splice(0).forEach(([, callback]) => callback());
  };
  return { document, press, env, settle };
}

test("the paper opens on its changes marked, with a switch to the clean paper", () => {
  const { document } = report();
  const data = () => document.querySelector(".paper-view object").getAttribute("data");
  assert.equal(data(), "paper-previews/paper/what-changed.pdf#navpanes=0&view=FitH");
  assert.deepEqual(
    [...document.querySelectorAll(".paper-modes button")].map(b => b.textContent),
    ["Changes marked", "Clean"],
  );
  document.querySelector('.paper-modes [data-pdf$="main.pdf"]').click();
  assert.equal(data(), "paper-previews/paper/main.pdf#navpanes=0&view=FitH");
  assert.deepEqual(
    [...document.querySelectorAll(".paper-modes button")].map(b => b.getAttribute("aria-pressed")),
    ["false", "true"],
  );
  // The fallback link stays inside the new frame and opens the PDF chosen.
  assert.equal(document.querySelector(".paper-view object a").getAttribute("href"),
    "paper-previews/paper/main.pdf");
});

test("the paper's bar reads title and file, then the switch, then the whole-window button at the far right", () => {
  const { document } = report();
  const bar = document.querySelector(".paper-bar");
  assert.deepEqual(
    [...bar.children].map(child => child.getAttribute("class")),
    ["paper-title", "paper-file", "paper-modes", "paper-expand"],
  );
  assert.equal(bar.querySelector(".paper-file").textContent, "paper/main.tex");
  assert.equal(bar.querySelector(".paper-title").textContent, "Paper");
});

test("the expand button gives the paper the whole window, and Esc gives the report back", () => {
  const { document, press, settle } = report();
  const view = document.querySelector(".paper-view");
  document.querySelector(".paper-expand").click();
  assert.equal(view.classList.contains("paper-full"), true);
  assert.equal(document.body.style.overflow, "hidden");
  press("Escape");
  settle();
  assert.equal(view.classList.contains("paper-full"), false);
  assert.equal(document.body.style.overflow, "");
});

test("Esc does nothing while the paper is not whole-window", () => {
  const { document, press, env, settle } = report();
  press("Escape");
  settle();
  assert.equal(document.querySelector(".paper-view").classList.contains("paper-full"), false);
  assert.deepEqual(env.scrolls, []);
});

test("the whole-window button takes the focus, so that Esc reaches the page, not the PDF", () => {
  const { document, env } = report();
  const expand = document.querySelector(".paper-expand");
  expand.click();
  assert.ok(env.focused.some(([element]) => element === expand), "the bar's button is focused");
});

test("leaving the whole window returns to the same place in the paper, with scroll anchoring off while the PDF settles", () => {
  const { document, press, env, settle } = report();
  const root = document.documentElement;
  // The reader is 200px into the paper's section.
  document.querySelector(".paper-expand").click();
  // The paper leaves the page, the page gets shorter, the browser clamps its scroll.
  env.scrollY = 0;
  press("Escape");
  assert.equal(root.style.overflowAnchor, "none", "anchoring is off at once");
  settle();
  assert.equal(env.scrolls.length > 0, true);
  assert.equal(env.scrolls.at(-1), 1000 + 200, "the place is the section's, plus the offset kept");
  assert.equal(env.scrolls.every(y => y === 1200), true, "every correction goes to the same place");
  assert.equal(root.style.overflowAnchor, "", "anchoring is back once the PDF has settled");
});

test("the paper's header is its title and file, then Changes marked · Clean, then the whole-window button", () => {
  const { document } = report();
  const head = document.querySelector("section.page-diff > .wc-head");
  assert.deepEqual([...head.querySelector(".wc-head-left").children].map(e => e.className), ["wc-title", "wc-file"]);
  assert.equal(head.querySelector(".wc-title").textContent, "Paper");
  assert.equal(head.querySelector(".wc-file").textContent, "paper/main.tex");
  const right = head.querySelector(".wc-head-right");
  assert.deepEqual([...right.children].map(e => e.className), ["wc-views", "wc-expand"]);
  assert.deepEqual([...right.querySelectorAll(".wc-views button")].map(b => b.textContent), ["Changes marked", "Clean"]);
  // The viewer's own bar follows the header, and is drawn only in the whole window.
  assert.equal(head.nextElementSibling.className, "paper-view");
});

test("the header's switch drives the viewer's two modes, and the viewer's own switch moves the header's", () => {
  const { document } = report();
  const data = () => document.querySelector(".paper-view object").getAttribute("data");
  const pressed = sel => [...document.querySelectorAll(sel)].map(b => b.getAttribute("aria-pressed"));
  const [marked, clean] = document.querySelectorAll(".wc-head .wc-views button");
  clean.click();
  assert.equal(data(), "paper-previews/paper/main.pdf#navpanes=0&view=FitH");
  assert.deepEqual(pressed(".wc-head .wc-views button"), ["false", "true"]);
  assert.deepEqual(pressed(".paper-modes button"), ["false", "true"]);
  marked.click();
  assert.equal(data(), "paper-previews/paper/what-changed.pdf#navpanes=0&view=FitH");
  assert.deepEqual(pressed(".wc-head .wc-views button"), ["true", "false"]);
  // In the whole window the viewer's own switch is the one used; the header follows.
  document.querySelector('.paper-modes [data-pdf$="main.pdf"]').click();
  assert.deepEqual(pressed(".wc-head .wc-views button"), ["false", "true"]);
});

test("the header's button gives the paper the whole window and follows it back; the viewer's own bar leaves it", () => {
  const { document, press, settle, env } = report();
  const view = document.querySelector(".paper-view");
  const button = document.querySelector(".wc-head .wc-expand");
  button.click();
  assert.equal(view.classList.contains("paper-full"), true);
  assert.equal(button.getAttribute("aria-pressed"), "true");
  // Focus is on the viewer's own bar, which shows now, so that Esc reaches the page.
  assert.equal(env.focused.at(-1)[0], document.querySelector(".paper-expand"));
  document.querySelector(".paper-expand").click();
  settle();
  assert.equal(view.classList.contains("paper-full"), false);
  assert.equal(button.getAttribute("aria-pressed"), "false");
  assert.equal(env.focused.at(-1)[0], button, "back in the page, the header's button has the focus");
  button.click();
  press("Escape");
  settle();
  assert.equal(view.classList.contains("paper-full"), false);
});

test("the viewer's own bar is hidden except in the whole window", () => {
  const css = [...parseHTML(generatedPage).document.querySelectorAll("style")].map(s => s.textContent).join("\n");
  assert.match(css, /\.wc-scope \.paper-view:not\(\.paper-full\) \.paper-bar \{ display: none; \}/);
});
