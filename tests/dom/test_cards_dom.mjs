import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

import { Event, parseHTML } from "linkedom";

const dir = new URL("../../plugins/asta-tools/skills/workspace/assets/_extensions/asta-pages/", import.meta.url);
const CORE = fs.readFileSync(new URL("asta-pages.js", dir), "utf8");
const TESTS = fs.readFileSync(new URL("tests.js", dir), "utf8");

// Cards as autolink.lua writes them: the page's store, keyed; a link names its card.
const STORE = {
  "m:node_3_1": {
    text: "node_3_1",
    foot: "Clicking node_3_1 opens the test.",
    sections: [
      { role: "Discovery", title: "Experiment 4 · node_3_1", href: "pages/0002-run.html#node-3-1", sub: "Seeded run",
        text: "Pre-lick activity separates false alarms.", clamp: 2, facts: ["belief 0.71 → 0.73", "surprisal 0.04"] },
      { role: "Verification", title: "Test node_3_1", href: "pages/0003-repro.html#test-node_3_1", sub: "Reproduction",
        test: { id: "node_3_1", summary: { verdict: "supported", effect: 0.28, p: 0.039, n_mice: 6 } },
        facts: ["dataset D1"], text: "Tests Theory one (supporting)", clamp: 1 },
    ],
  },
  "m:G1": {
    text: "G1",
    sections: [
      { role: "Gap G1", title: "does alpha hold?", title_clamp: 1, href: "pages/0004-gaps.html#query-1", facts: ["4 theories"],
        tally: [
          { id: "T1", summary: { meets_threshold: true } }, { id: "T2", summary: { meets_threshold: false } },
          { id: "T3", summary: { meets_threshold: false } }, { id: "T4", summary: { verdict: "undecided" } },
        ] },
      { links: [{ label: "Gap map entry", href: "pages/0004-gaps.html#doc-gaps-g1" }] },
    ],
  },
  "m:Theory one": {
    text: "Theory one",
    sections: [{ role: "Theory", title: "Theory one", href: "pages/0004-gaps.html#theory-1", text: "Alpha holds.", clamp: 4,
      tests: [{ id: "T1", summary: { meets_threshold: true } }], facts: ["4 supporting", "1 conflicting findings"] }],
  },
  "x:https://example.org/d": {
    text: "data", foot: "Opens in a new tab.",
    sections: [{ role: "Dataset", title: "Example data", sub: "Released by Example Lab", text: "Used for: T1", clamp: 3 }],
  },
  "e:E-1": {
    text: "claim",
    sections: [{ role: "Evidence", quote: "alpha held", clamp: 4 },
      { role: "Paper", title: "A study", sub: "A. Author · 2020", links: [{ label: "DOI", href: "https://doi.org/10.1/x", external: true }] }],
  },
  "g:fig-one": {
    text: "Figure 1",
    sections: [{ role: "Figure", title: "Figure 1", href: "#fig-one", image: "figures/one.png", text: "Alpha.", clamp: 3, facts: ["audit: PASS"] }],
  },
  "f:notes/a.md": { text: "a.md", file: true, sections: [{ role: "File", title: "a.md", sub: "notes", facts: ["12 B"] }] },
};
const storeTag = store => `<script type="application/json" class="asta-cards-data">${JSON.stringify(store)}</script>`;
const link = (key, text, href = "#") => `<a href="${href}" class="asta-al" data-asta-card="${key}" title="native">${text}</a>`;

function page(body, { url = "http://site.test/index.html", framed = false } = {}) {
  const { document } = parseHTML(`<!doctype html><html><body><main id="quarto-document-content">${body}</main><p id="elsewhere">x</p></body></html>`);
  const window = { addEventListener() {}, innerHeight: 800, scrollY: 0, scrollX: 0 };
  window.top = framed ? {} : window;
  vm.runInNewContext(TESTS, { window, document, location: { hash: "" } });
  vm.runInNewContext(CORE, { window, document, location: { href: url, hash: "" }, history: {}, URL, console, setTimeout, clearTimeout });
  const fire = (el, type, props = {}) => { const ev = new Event(type, { bubbles: true }); Object.assign(ev, props); el.dispatchEvent(ev); return ev; };
  const open = sel => { fire(document.querySelector(sel), "focusin"); return window.AstaPages.cards.current(); };
  return { document, window, cards: window.AstaPages.cards, fire, open };
}
const wait = ms => new Promise(r => setTimeout(r, ms));
const roles = card => [...card.querySelectorAll(".ap-al-role")].map(x => x.textContent);

test("one renderer draws every kind of card from the page's store", () => {
  const p = page(`<p>${link("m:node_3_1", "node_3_1")} ${link("m:G1", "G1")} ${link("m:Theory one", "Theory one")}
    ${link("x:https://example.org/d", "data", "https://example.org/d")} <span class="ev" data-asta-card="e:E-1" tabindex="0">claim</span>
    ${link("g:fig-one", "Figure 1", "#fig-one")} ${link("f:notes/a.md", "a.md", "../notes/a.md")}</p>${storeTag(STORE)}`);
  let c = p.open('[data-asta-card="m:node_3_1"]');
  assert.deepEqual(roles(c), ["Discovery", "Verification"]);
  assert.deepEqual([...c.querySelectorAll("a.ap-al-go")].map(a => a.getAttribute("href")),
    ["http://site.test/pages/0002-run.html#node-3-1", "http://site.test/pages/0003-repro.html#test-node_3_1"]);
  assert.match(c.textContent, /belief 0\.71 → 0\.73 · surprisal 0\.04/);
  assert.equal(c.querySelector(".ap-v").textContent, "supported");
  assert.match(c.textContent, /effect 0\.28 · p 0\.039 · 6 mice/);
  assert.match(c.textContent, /dataset D1/);
  assert.equal(c.querySelector(".ap-al-foot").textContent, "Clicking node_3_1 opens the test.");

  c = p.open('[data-asta-card="m:G1"]');
  assert.match(c.textContent, /4 theories/);
  assert.match(c.textContent, /4 tests: 1 met · 2 not met · 1 undecided/);
  assert.equal(c.querySelector(".ap-al-links a").textContent, "Gap map entry →");

  c = p.open('[data-asta-card="m:Theory one"]');
  assert.deepEqual([...c.querySelectorAll(".ap-al-chips .ap-chip")].map(x => x.textContent), ["T1 · met"]);
  assert.equal(c.querySelector(".ap-al-text").getAttribute("style"), "-webkit-line-clamp:4");

  c = p.open('[data-asta-card="x:https://example.org/d"]');
  assert.deepEqual(roles(c), ["Dataset"]);
  assert.equal(c.querySelector(".ap-al-foot").textContent, "Opens in a new tab.");

  c = p.open('[data-asta-card="e:E-1"]');
  assert.equal(c.querySelector(".ap-al-quote").textContent, "“alpha held”");
  assert.equal(c.querySelector(".ap-al-links a").getAttribute("target"), "_blank");

  c = p.open('[data-asta-card="g:fig-one"]');
  assert.equal(c.querySelector("img.ap-al-thumb").getAttribute("src"), "http://site.test/figures/one.png");

  c = p.open('[data-asta-card="f:notes/a.md"]');
  assert.equal(c.querySelector(".ap-al-foot").textContent, "Opens the file.");
});

test("a workspace file says where it opens: Files in the app's frame, GitHub once deployed", () => {
  const framed = page(`<p>${link("f:notes/a.md", "a.md", "../notes/a.md")}</p>${storeTag(STORE)}`, { framed: true });
  assert.equal(framed.open("[data-asta-card]").querySelector(".ap-al-foot").textContent, "Opens in Files.");
  const pages = page(`<p>${link("f:notes/a.md", "a.md", "https://github.com/o/r/blob/main/notes/a.md")}</p>${storeTag(STORE)}`);
  assert.equal(pages.open("[data-asta-card]").querySelector(".ap-al-foot").textContent, "Opens on GitHub.");
});

test("a link with a card gives up its native title and Quarto's preview; the evidence popover gives way", async () => {
  const p = page(`<p>${link("m:G1", "G1")} <span class="ev" data-asta-card="e:E-1"><span class="ev-pop">quote</span></span></p>${storeTag(STORE)}`);
  const a = p.document.querySelector("a[data-asta-card]");
  let destroyed = false;
  a._tippy = { destroy() { destroyed = true; } };
  await wait(5);
  assert.equal(a.getAttribute("title"), null);
  assert.equal(destroyed, true);
  assert.ok(p.document.documentElement.classList.contains("asta-cards"), "asta-pages.css hides .ev-pop under html.asta-cards");
});

test("Esc and a click elsewhere close the card", () => {
  const p = page(`<p>${link("m:G1", "G1")}</p>${storeTag(STORE)}`);
  const a = p.document.querySelector("a[data-asta-card]");
  p.fire(a, "focusin");
  p.fire(p.document.body, "keydown", { key: "Escape" });
  assert.equal(p.cards.current(), null);
  assert.equal(a.getAttribute("aria-expanded"), "false");
  p.fire(a, "focusin");
  p.fire(p.document.getElementById("elsewhere"), "pointerdown", { pointerType: "mouse" });
  assert.equal(p.cards.current(), null);
});

test("hover opens after a moment; the card stays while the pointer is on it, and closes after it leaves", async () => {
  const p = page(`<p>${link("m:G1", "G1")}</p>${storeTag(STORE)}`);
  const a = p.document.querySelector("a[data-asta-card]");
  p.fire(a, "mouseover");
  assert.equal(p.cards.current(), null, "not at once");
  await wait(160);
  const card = p.cards.current();
  assert.ok(card);
  p.fire(a, "mouseout", { relatedTarget: card.querySelector(".ap-al-item") });
  p.fire(card.querySelector(".ap-al-item"), "mouseover");
  await wait(400);
  assert.equal(p.cards.current(), card);
  p.fire(card.querySelector(".ap-al-item"), "mouseout", { relatedTarget: p.document.getElementById("elsewhere") });
  assert.equal(p.cards.current(), card, "not at once");
  await wait(400);
  assert.equal(p.cards.current(), null);
});

test("a tap opens the card instead of following the link; a second tap follows it", () => {
  const p = page(`<p>${link("m:G1", "G1")}</p>${storeTag(STORE)}`);
  const a = p.document.querySelector("a[data-asta-card]");
  p.fire(a, "pointerdown", { pointerType: "touch" });
  assert.equal(p.fire(a, "click").defaultPrevented, true);
  assert.ok(p.cards.current());
  p.fire(a, "pointerdown", { pointerType: "touch" });
  assert.equal(p.fire(a, "click").defaultPrevented, false);
});

test("a page appended to a flow's feed: its own store, its links from that page", () => {
  const other = { "m:G1": { text: "G1", sections: [{ role: "Gap G1", title: "other", href: "pages/x.html#query-2" }] } };
  const p = page(`<p>${link("m:G1", "G1")}</p>${storeTag(STORE)}` +
    `<section class="asta-flow-page" data-asta-url="http://site.test/other/review.html"><p>${link("m:G1", "G1")}</p>${storeTag(other)}</section>`);
  p.fire(p.document.querySelectorAll("a[data-asta-card]")[1], "focusin");
  const go = p.cards.current().querySelector("a.ap-al-go");
  assert.equal(go.textContent, "other →");
  assert.equal(go.getAttribute("href"), "http://site.test/other/pages/x.html#query-2");
});
