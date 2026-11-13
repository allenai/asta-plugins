import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseHTML } from "linkedom";

// A page of What changed as the product builds it, with the project's own files at both
// commits, and a slide deck beside it: the one header and its control, as a reader uses them.
const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const root = fs.mkdtempSync(path.join(os.tmpdir(), "what-changed-views-dom-"));
const write = (file, text) => {
  fs.mkdirSync(path.dirname(path.join(root, file)), { recursive: true });
  fs.writeFileSync(path.join(root, file), text);
};
const shell = (body) => `<title>Notes – Site</title><main>${body}</main>`;
write("old/page.html", shell(
  "<h2>Heading</h2><p>Removed whole paragraph here.</p><p>Keep paragraph.</p>" +
  '<p>Tea is <a href="https://old.example/x">good</a> today.</p>'));
write("new/page.html", shell(
  "<h2>Heading</h2><p>Keep paragraph.</p>" +
  '<p>Tea is <a href="https://new.example/y">great</a> today.</p><p>Brand new paragraph.</p>'));
write("old/other.html", shell("<p>Same.</p>"));
write("new/other.html", shell("<p>Same.</p>"));
write("oldsrc/other.qmd", "Same.\n");
write("newsrc/other.qmd", "Same.\n<!-- reviewer: keep this note -->\n");
write("oldsrc/page.qmd", "# Notes\n\nKeep paragraph.\n\nTea is [good](https://old.example/x) today.\n");
write("newsrc/page.qmd",
  "# Notes\n\nKeep paragraph.\n<!-- reviewer: soften this -->\n\n" +
  "Tea is [great](https://new.example/y) today.\n\nBrand new paragraph.\n");
const deck = (word) =>
  '<html><head></head><body><div class="reveal"><div class="slides">' +
  `<section id="a"><h2>Hello ${word}</h2></section><section id="b"><h2>Same</h2></section>` +
  "</div></div></body></html>";
write("old/deck.html", deck("old"));
write("new/deck.html", deck("new"));
write("oldsrc/deck.qmd", "---\ntitle: Deck\n---\n\n# Hello old\n\n# Same\n");
write("newsrc/deck.qmd", "---\ntitle: Deck\n---\n\n# Hello new\n\n# Same\n");
const out = path.join(root, "what-changed.html");
const generated = spawnSync("python3", [
  "-I", "plugins/asta-tools/skills/workspace/assets/what-changed.py",
  "--old", path.join(root, "old"), "--new", path.join(root, "new"), "--out", out,
  "--old-source", path.join(root, "oldsrc"), "--new-source", path.join(root, "newsrc"),
  "--render-decks", path.join(root, "new/decks"),
], { cwd: repoRoot, encoding: "utf8" });
assert.equal(generated.status, 0, generated.stderr);
const built = fs.readFileSync(out, "utf8");
// The page's script that sets the views, and a deck's own script (the one that sets its view).
const scripts = [...built.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const viewsScript = scripts.find((s) => s.includes("wcView") && s.includes("wc-views"));
const deckScript = scripts.find((s) => s.includes("root.wcView = setView"));
assert.ok(viewsScript, "the page must carry the script that sets the views");

// linkedom has no layout: boxes are stand-ins the tests set, scrolling is recorded.
function report({ layout } = {}) {
  const { document, window } = parseHTML(built);
  const env = { scrolls: [] };
  window.HTMLElement.prototype.getBoundingClientRect = function () {
    return layout ? layout(this, document) : { top: 0, bottom: 0, width: 0, height: 0 };
  };
  const win = { scrollBy: (x, y) => env.scrolls.push(y) };
  Function("document", "window", viewsScript)(document, win);
  return { document, env, section: document.getElementById("p-page-html") };
}
const click = (root, view) => root.querySelector(`.wc-head [data-wc-view="${view}"]`).click();
const text = (el) => el.textContent.replace(/\s+/g, " ").trim();

test("each diff has one header: title linking to the page, file, then the control", () => {
  const { section, document } = report();
  const head = section.firstElementChild;
  assert.equal(head.className, "wc-head", "the header comes first in its section");
  const left = head.querySelector(".wc-head-left"), right = head.querySelector(".wc-head-right");
  assert.deepEqual([...left.children].map((e) => e.className), ["wc-title", "wc-file"]);
  assert.equal(left.querySelector(".wc-title a").getAttribute("href"), "page.html");
  assert.equal(text(left.querySelector(".wc-title")), "Notes", "the site's name is left out");
  assert.equal(text(left.querySelector(".wc-file")), "page.html");
  // The three diffs, then Clean, the one view that is no diff.
  assert.deepEqual([...right.querySelectorAll("button")].map(text),
    ["Source", "Changes marked", "Before / after", "Clean"]);
  assert.equal(right.querySelector('[aria-pressed="true"]').textContent, "Changes marked");
  // It replaces the section's own heading and its file legend line.
  assert.equal(section.querySelectorAll("h2.wc-title").length, 1);
  assert.equal(section.querySelector(".legend"), null);
  assert.equal(section.querySelector(":scope > h2"), null);
  assert.equal(document.querySelectorAll("section.page-diff > .wc-head").length, 3);
});

test("the header is kept at the top of the window while its section scrolls by", () => {
  const css = [...parseHTML(built).document.querySelectorAll("style")].map((s) => s.textContent).join("\n");
  const rule = css.match(/\.wc-scope \.wc-head \{([^}]*)\}/)[1];
  assert.match(rule, /position: sticky/);
  assert.match(rule, /top: 0/);
  assert.match(rule, /background: var\(--wc-bg\)/);
  // A header with a background of its own, in the page's mode, so that text never shows through.
  assert.match(css, /--wc-bg: var\(--bs-body-bg, #fff\)/);
  // Nothing between the header and the section's edge cuts sticky off (no overflow on the section).
  const section = css.match(/\.wc-scope section\.page-diff \{([^}]*)\}/)[1];
  assert.doesNotMatch(section, /overflow/);
  // The header sits in the section, not in what scrolls inside it.
  const { section: s } = report();
  assert.equal(s.querySelector(".diff-body .wc-head"), null);
});

test("Changes marked is the default view, and the only one on the page until another is asked for", () => {
  const { section } = report();
  assert.equal(section.querySelector(".diff-body").hidden, false);
  assert.equal(section.querySelector(".wc-source").hidden, true);
  assert.equal(section.querySelector(".wc-clean"), null);
  assert.equal(section.querySelector(".wc-ba"), null);
});

test("Clean is the new version as readers will see it: no mark of What changed is left", () => {
  const { section } = report();
  click(section, "clean");
  const clean = section.querySelector(".wc-clean");
  assert.equal(clean.hidden, false);
  assert.equal(section.querySelector(".diff-body").hidden, true);
  assert.equal(clean.querySelectorAll("ins, del, [class*='wc-']").length, 0, clean.innerHTML);
  assert.equal(clean.querySelector("[data-wc-was]"), null);
  assert.deepEqual([...clean.querySelectorAll("p")].map(text),
    ["Keep paragraph.", "Tea is great today.", "Brand new paragraph."]);
  assert.equal(clean.querySelector("a").getAttribute("href"), "https://new.example/y");
  assert.equal(clean.querySelector("a").getAttribute("title"), null);
  assert.equal(section.querySelector('[aria-pressed="true"]').textContent, "Clean");
});

test("Before / after sets old and new side by side, each marked only as its own", () => {
  const { section } = report();
  click(section, "before");
  const [before, after] = section.querySelectorAll(".wc-ba-col");
  assert.deepEqual([...section.querySelectorAll(".wc-ba-label")].map(text), ["Before", "After"]);
  assert.deepEqual([...before.querySelectorAll("p")].map(text),
    ["Removed whole paragraph here.", "Keep paragraph.", "Tea is good today."]);
  assert.deepEqual([...after.querySelectorAll("p")].map(text),
    ["Keep paragraph.", "Tea is great today.", "Brand new paragraph."]);
  // A link keeps the target it had on each side.
  assert.equal(before.querySelector("a").getAttribute("href"), "https://old.example/x");
  assert.equal(after.querySelector("a").getAttribute("href"), "https://new.example/y");
  for (const col of [before, after]) {
    assert.equal(col.lastElementChild.querySelectorAll("ins, del, [class*='wc-']").length, 0);
  }
});

test("Source is the page's own source at both commits, old line above new, with the file's name in the header", () => {
  const { section } = report();
  click(section, "source");
  const source = section.querySelector(".wc-source");
  assert.equal(source.hidden, false);
  assert.equal(section.querySelector(".diff-body").hidden, true);
  assert.equal(text(section.querySelector(".wc-file")), "page.qmd");
  const rows = [...source.querySelectorAll(".wc-ln")];
  const old = rows.findIndex((r) => r.classList.contains("wc-edit-old"));
  assert.ok(old >= 0 && rows[old + 1].classList.contains("wc-edit-new"));
  assert.match(text(rows[old]), /good.*old.*x/);
  assert.match(text(rows[old + 1]), /great.*new.*y/);
  assert.ok(rows.some((r) => text(r).includes("reviewer: soften this")));
  // Back to the page: the file is the page's again.
  click(section, "marked");
  assert.equal(text(section.querySelector(".wc-file")), "page.html");
  assert.equal(source.hidden, true);
});

test("a page whose only change is in its source says so in its header and opens its Source", () => {
  const { document } = report();
  const only = document.getElementById("p-other-html");
  const head = only.firstElementChild;
  assert.equal(head.className, "wc-head");
  // Plain detail after the file: title and file adjacent, no tag in header or overview.
  assert.equal(head.querySelector(".tag"), null);
  const title = head.querySelector(".wc-title");
  assert.equal(title.nextElementSibling.className, "wc-file");
  assert.equal(title.nextElementSibling.nextElementSibling.className, "wc-detail");
  assert.equal(text(title.nextElementSibling.nextElementSibling), "only its source changed");
  assert.equal(document.querySelector('nav.toc a[href="#p-other-html"]').parentElement.querySelector(".tag"), null);
  assert.deepEqual([...head.querySelectorAll(".wc-views button")].map(text),
    ["Source", "Changes marked", "Before / after", "Clean"]);
  assert.equal(head.querySelector('.wc-views [aria-pressed="true"]').textContent, "Changes marked");
  assert.equal(only.querySelector(".wc-source").hidden, true);
  click(only, "source");
  assert.equal(only.querySelector(".wc-source").hidden, false);
  assert.equal(only.querySelector('.wc-views [aria-pressed="true"]').textContent, "Source");
  assert.ok([...only.querySelectorAll(".wc-source .wc-ln")].some((r) => text(r).includes("reviewer: keep this note")));
  assert.equal(text(only.querySelector(".wc-file")), "other.qmd");
  // The overview lists it, and nothing in the report counts or marks "only in the source".
  assert.match(text(document.querySelector("nav.toc")), /other\.html · only its source changed/);
  assert.doesNotMatch(built, /only in the source|data-wc-unseen|wc-unseen|data-wc-goto/);
});

test("a switch keeps the reader's place: the block at the top of the window is put back at the same height", () => {
  // The marked page starts 130px above the window, its blocks 100px apart; the other
  // views start 50px below its top. The header's bottom is 40px.
  const leaf = "p, li, h1, h2, h3, h4, h5, h6, tr, pre, figcaption, dt, dd";
  const layout = (el) => {
    if (el.classList.contains("wc-head")) return { top: 0, bottom: 40, width: 10, height: 40 };
    const view = el.closest(".diff-body, .wc-clean, .wc-ba-after");
    if (!view) return { top: 0, bottom: 0, width: 0, height: 0 };
    const top = (view.matches(".diff-body") ? -130 : 50) + 100 * [...view.querySelectorAll(leaf)].indexOf(el);
    return { top, bottom: top + 90, width: 100, height: 90 };
  };
  // Marked: heading (-130..-40, above the header), the removed paragraph (-30..60): the block
  // at the top, 70px above the header's bottom. Clean has no copy of it, so the next block
  // it has, "Keep paragraph." (the second block there: top 150), goes where it was.
  const { section, env } = report({ layout });
  click(section, "clean");
  assert.deepEqual(env.scrolls, [150 - (40 - 70)]);
  // From Clean, whose top block is its heading (top 50, 10px below the header), back to
  // the marked page, which has the heading at -130: put 10px below the header again.
  env.scrolls.length = 0;
  click(section, "marked");
  assert.deepEqual(env.scrolls, [-130 - (40 + 10)]);
});

test("a deck takes the same header and control, and its own bar is folded into it", () => {
  const { section } = report();
  const deckSection = [...section.ownerDocument.querySelectorAll("section.page-diff")]
    .find((s) => s.querySelector(".deck-review"));
  assert.ok(deckSection, "the deck has a section");
  assert.equal(deckSection.firstElementChild.className, "wc-head");
  assert.equal(deckSection.querySelector(".dr-bar"), null);
  assert.equal(deckSection.querySelector(".dr-seg"), null);
  const head = deckSection.querySelector(".wc-head");
  assert.equal(text(head.querySelector(".wc-file")), "deck.html");
  assert.deepEqual([...head.querySelectorAll(".wc-views button")].map(text),
    ["Source", "Changes marked", "Before / after", "Clean"]);
  assert.equal(head.querySelector('.wc-views [aria-pressed="true"]').textContent, "Changes marked");
});

test("the deck's header sets the deck's view, and Source takes the deck's place", () => {
  const { document, section } = report();
  const deckSection = [...document.querySelectorAll("section.page-diff")].find((s) => s.querySelector(".deck-review"));
  const live = deckSection.querySelector(".deck-review");
  // linkedom has no layout: a frame is loaded when its view is the deck's.
  const win = { scrollBy() {}, addEventListener() {} };
  // A frame in linkedom has no window: stand in for a sandboxed frame, which takes messages.
  Object.defineProperty(document.defaultView.HTMLElement.prototype, "contentWindow", {
    configurable: true,
    get: () => ({ postMessage() {} }),
  });
  Function("document", "window", "setTimeout", deckScript)(document, win, () => 0);
  assert.equal(typeof live.wcView, "function");
  for (const view of ["clean", "before", "marked"]) {
    click(deckSection, view);
    assert.equal(live.getAttribute("data-view"), view);
    assert.equal(live.hidden, false);
  }
  click(deckSection, "source");
  assert.equal(live.hidden, true);
  assert.equal(deckSection.querySelector(".wc-source").hidden, false);
  assert.equal(text(deckSection.querySelector(".wc-file")), "deck.qmd");
  click(deckSection, "before");
  assert.equal(live.hidden, false);
  assert.equal(live.getAttribute("data-view"), "before");
  assert.equal(deckSection.querySelector(".wc-source").hidden, true);
  void section;
});

test.after(() => fs.rmSync(root, { recursive: true, force: true }));

// --- Clean and Before / after hold each version as published, never the marked diff rebuilt.
// The review's pages: an author's own ins and del, a formatting change, a removed link,
// and a page that tries to run something.
const vroot = fs.mkdtempSync(path.join(os.tmpdir(), "what-changed-versions-dom-"));
const vwrite = (file, text) => {
  fs.mkdirSync(path.dirname(path.join(vroot, file)), { recursive: true });
  fs.writeFileSync(path.join(vroot, file), text);
};
const authored = (end) => `<p>Dose: <del>5 mg</del> <ins>10 mg</ins>. ${end} conclusion.</p>`;
vwrite("old/dose.html", shell(authored("Old")));
vwrite("new/dose.html", shell(authored("New")));
vwrite("old/format.html", shell("<p>The <em>sample</em> is old.</p>"));
vwrite("new/format.html", shell("<p>The <strong>sample</strong> is new.</p>"));
vwrite("old/link.html", shell('<p>The <a href="https://example.org/paper">paper</a> is old.</p>'));
vwrite("new/link.html", shell("<p>The paper is new.</p>"));
const hostile = (word) =>
  `<p>${word} text</p><img src="x.png" onerror="parent.pwned=1"><script>parent.pwned=2</script>` +
  '<a href="javascript:parent.pwned=3">go</a></template><script>parent.pwned=4</script>';
vwrite("old/hostile.html", shell(hostile("Old")));
vwrite("new/hostile.html", shell(hostile("New")));
const vout = path.join(vroot, "what-changed.html");
const vgenerated = spawnSync("python3", [
  "-I", "plugins/asta-tools/skills/workspace/assets/what-changed.py",
  "--old", path.join(vroot, "old"), "--new", path.join(vroot, "new"), "--out", vout,
], { cwd: repoRoot, encoding: "utf8" });
assert.equal(vgenerated.status, 0, vgenerated.stderr);
const vbuilt = fs.readFileSync(vout, "utf8");
const vscript = [...vbuilt.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1])
  .find((s) => s.includes("wcView") && s.includes("wc-views"));

function versions(extra = {}) {
  const { document, window } = parseHTML(vbuilt);
  Function("document", "window", vscript)(document, { scrollBy() {}, pwned: undefined, ...extra });
  const open = (name, view) => {
    const section = document.getElementById(`p-${name}-html`);
    click(section, view);
    return section;
  };
  return { document, window, open };
}
const inner = (el) => el.innerHTML.replace(/\s+/g, " ").trim();

test("an author's own ins and del are in Clean and in both sides of Before / after", () => {
  const { open } = versions();
  const clean = open("dose", "clean").querySelector(".wc-clean");
  assert.match(inner(clean), /<del>5 mg<\/del> <ins>10 mg<\/ins>\. New conclusion\./);
  const section = open("dose", "before");
  const [before, after] = [...section.querySelectorAll(".wc-ba-body")];
  assert.match(inner(before), /<del>5 mg<\/del> <ins>10 mg<\/ins>\. Old conclusion\./);
  assert.match(inner(after), /<del>5 mg<\/del> <ins>10 mg<\/ins>\. New conclusion\./);
});

test("a formatting change shows its own formatting on each side, and Clean keeps no mark of it", () => {
  const { open } = versions();
  const clean = open("format", "clean").querySelector(".wc-clean");
  assert.equal(clean.querySelectorAll("strong").length, 1);
  assert.equal(clean.querySelectorAll("em").length, 0);
  assert.equal(clean.querySelector("[title]"), null, "no title='formatting changed'");
  const [before, after] = [...open("format", "before").querySelectorAll(".wc-ba-body")];
  assert.equal(before.querySelectorAll("em").length, 1);
  assert.equal(before.querySelectorAll("strong").length, 0);
  assert.equal(after.querySelectorAll("strong").length, 1);
  assert.equal(after.querySelectorAll("em").length, 0);
});

test("a removed link is a link in Before, and plain words in Clean and After", () => {
  const { open } = versions();
  const [before, after] = [...open("link", "before").querySelectorAll(".wc-ba-body")];
  assert.equal(before.querySelector("a").getAttribute("href"), "https://example.org/paper");
  assert.equal(after.querySelector("a"), null);
  assert.equal(open("link", "clean").querySelector(".wc-clean a"), null);
  assert.equal(text(before.querySelector("p")), "The paper is old.");
});

test("what a compared page tries to run is not in any view, and no template is left open", () => {
  const { open, document } = versions();
  for (const view of ["clean", "before"]) {
    const section = open("hostile", view);
    const drawn = [...section.querySelectorAll(".wc-clean, .wc-ba-body")];
    assert.ok(drawn.length >= 1);
    for (const body of drawn) {
      assert.equal(body.querySelector("script, [onerror], [onload]"), null, body.innerHTML);
      assert.ok(![...body.querySelectorAll("a")].some((a) => /^javascript:/i.test(a.getAttribute("href") || "")));
      assert.match(text(body), /text/);
    }
  }
  const section = document.getElementById("p-hostile-html");
  assert.equal(section.querySelectorAll("template").length, 2);
  assert.equal(section.querySelectorAll("template script, template [onerror]").length, 0);
});

test("a view is given to the page's own scripts once it is in the page: equations typeset, diagrams drawn", () => {
  const typeset = [], drawn = [];
  const { open } = versions({
    MathJax: { typesetPromise: (roots) => { typeset.push(...roots); return Promise.resolve(); } },
    wcMermaid: (root) => drawn.push(root),
  });
  const clean = open("dose", "clean").querySelector(".wc-clean");
  assert.deepEqual(typeset, [clean]);
  assert.deepEqual(drawn, [clean]);
  typeset.length = 0;
  drawn.length = 0;
  const bodies = [...open("format", "before").querySelectorAll(".wc-ba-body")];
  assert.deepEqual(typeset, bodies);
  assert.deepEqual(drawn, bodies);
  // once, however often the views are switched
  open("format", "marked");
  open("format", "before");
  assert.equal(typeset.length, 2);
});

test.after(() => fs.rmSync(vroot, { recursive: true, force: true }));

