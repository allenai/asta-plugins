import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

import { DOMParser, Event, parseHTML } from "linkedom";

const dir = new URL("../../plugins/asta-tools/skills/workspace/assets/_extensions/asta-pages/", import.meta.url);
const read = name => fs.readFileSync(new URL(name, dir), "utf8");
const CORE = read("asta-pages.js");
const TESTS = read("tests.js");
const THEORIES = read("theories.js");

const ORIGIN = "http://site.test";
const PAGES = `${ORIGIN}/_site/pages/`;

// A test folder's row, in the shape asta-pages.lua embeds (links relative to the rendered page).
const testRow = id => ({ id, href: `../../.asta/flows/0001-demo/04-tests/${id}/`, summary: { meets_threshold: true } });
const testsPanel = (id, tests) =>
  `<div class="asta-panel asta-tests" data-asta-data="${id}"></div>\n` +
  `<script type="application/json" class="asta-tests-data" id="${id}">${JSON.stringify({ tests, others: [] })}</script>`;
const theory = (id, name) => ({ id, name, query: "Why?", statements: [], supporting: 0, conflicting: 0 });
const theoriesPanel = theories =>
  `<div class="asta-panel asta-theories"></div>\n` +
  `<script type="application/json" class="asta-theories-data" id="asta-theories-data" data-asta-source="data/t.json">${JSON.stringify({ theories })}</script>`;

// The scaffold's sidebar: the front page, then the workflow pages flat, by file name (run order),
// on a page at `up` from the site's root ("../" for a workflow page). Quarto's script links the
// front page as the site's folder. `extra` links follow (a site elsewhere, a page listed twice).
const sidebarItem = (href, text) => `<li class="sidebar-item"><div class="sidebar-item-container"><a href="${href}" class="sidebar-item-text sidebar-link">${text}</a></div></li>`;
const sidebar = (up = "../", extra = []) => `<nav id="quarto-sidebar"><ul>` + sidebarItem(up, "Review") +
  [["0001-explore.html", "A"], ["0002-repro.html", "B"], ["0003-gaps.html", "C"], ["0004-review.html", "D"]]
    .map(([f, t]) => sidebarItem(`${up}pages/${f}`, t)).join("") +
  extra.map(([h, t]) => sidebarItem(h, t)).join("") + "</ul></nav>";

// A rendered page: Quarto's title block, a step's heading, the panels, and the feed's and the
// sidebar's data (asta-pages.lua writes them on every page it runs on).
function pageHtml(title, body, flow, { up = "../", extra = [], sections = null, toc = "" } = {}) {
  return `<!doctype html><html><head><title>${title} – Demo</title>` +
    `<script src="${up}site_libs/quarto-contrib/asta-pages-core-0.1.0/asta-pages.js"></script></head><body>` + sidebar(up, extra) +
    (toc ? `<nav id="TOC" role="doc-toc"><ul>${toc}</ul></nav>` : "") +
    `<main class="content" id="quarto-document-content"><header id="title-block-header"><h1 class="title">${title}</h1></header>` +
    `<section id="tests" class="level2"><h2>Tests</h2>${body}</section></main>` +
    (flow ? `<script type="application/json" id="asta-flow">${JSON.stringify(flow)}</script>` : "") +
    (sections ? `<script type="application/json" id="asta-sections">${JSON.stringify(sections)}</script>` : "") +
    "</body></html>";
}

// A browser for the page at `url`: its address and history, the scripts, and the other pages
// the server holds (fetch answers from `site`). IntersectionObserver is the test's to fire.
function browse(url, html, site = {}) {
  const { document } = parseHTML(html);
  const listeners = {};
  let href = url;
  const location = {
    get href() { return href; },
    get hash() { const i = href.indexOf("#"); return i < 0 || i === href.length - 1 ? "" : href.slice(i); },
    get origin() { return ORIGIN; },
  };
  const entries = [href];
  const go = u => { href = new URL(u, href).href; };
  const history = {
    state: null,
    pushState: (_, __, u) => { go(u); entries.push(href); },
    replaceState: (_, __, u) => { go(u); entries[entries.length - 1] = href; },
  };
  const fetched = [];
  const observed = [];
  class IntersectionObserver {
    constructor(fn) { this.fn = fn; }
    observe(el) { observed.push({ el, fire: () => this.fn([{ isIntersecting: true, target: el }]) }); }
    unobserve() {}
  }
  const window = {
    __listeners: listeners,
    addEventListener: (type, fn) => (listeners[type] ??= []).push(fn),
    innerHeight: 800, scrollY: 0, IntersectionObserver,
  };
  const fetch = u => {
    fetched.push(u.replace(ORIGIN, ""));
    const text = site[u];
    return Promise.resolve(text == null ? { ok: false, status: 404 } : { ok: true, status: 200, text: () => Promise.resolve(text) });
  };
  const ctx = { window, document, location, history, fetch, URL, DOMParser, console, setTimeout, clearTimeout };
  for (const code of [CORE, TESTS, THEORIES]) vm.runInNewContext(code, ctx);
  const dispatch = type => (listeners[type] ?? []).forEach(fn => fn());
  const visit = u => { go(u); entries.push(href); dispatch("hashchange"); };
  // Back, as a browser does it: popstate, then hashchange.
  const back = () => { entries.pop(); href = entries[entries.length - 1]; dispatch("popstate"); dispatch("hashchange"); };
  const settle = () => new Promise(r => setTimeout(r, 0)).then(() => new Promise(r => setTimeout(r, 0)));
  // Reaching the end of what is loaded: the sentinel's observer fires, then the fetch settles.
  const reachEnd = async () => { observed[observed.length - 1].fire(); for (let i = 0; i < 5; i++) await settle(); };
  return { document, window, location, history, entries, fetched, visit, back, reachEnd, AstaPages: window.AstaPages };
}

// What every page carries: where the site's root is, from the page.
const FLOW = (up = "../") => ({ format: "asta-pages/flow@3", site: up });
const ROOT = `${ORIGIN}/_site/`;

const SITE = {
  [PAGES + "0002-repro.html"]: pageHtml("B", '<p><a class="file" href="../../.asta/flows/0002-b/notes.md">notes.md</a></p>' +
    testsPanel("asta-tests-1", [testRow("T1"), testRow("T2")]) + '<section id="résumé-état" class="level2"><h2>Résumé, état</h2></section>', FLOW(),
    { toc: '<li><a href="#tests">Tests</a></li><li><a href="#r%C3%A9sum%C3%A9-%C3%A9tat">Résumé, état</a></li>' }),
  [PAGES + "0003-gaps.html"]: pageHtml("C", theoriesPanel([theory("theory-1", "C one"), theory("theory-2", "C two")]), FLOW()),
  [PAGES + "0004-review.html"]: pageHtml("D", "", FLOW()),
};

test("the next pages load in the sidebar's order, each under a divider, to the last", async () => {
  const b = browse(PAGES + "0001-explore.html", pageHtml("A", testsPanel("asta-tests-1", [testRow("T1")]), FLOW()), SITE);
  const { document } = b;
  assert.equal(document.querySelectorAll(".asta-flow-page").length, 0, "nothing is fetched before the end of the page");
  assert.deepEqual(b.fetched, []);

  await b.reachEnd();
  await b.reachEnd();
  await b.reachEnd();
  assert.deepEqual(b.fetched, ["/_site/pages/0002-repro.html", "/_site/pages/0003-gaps.html", "/_site/pages/0004-review.html"]);
  const sections = [...document.querySelectorAll(".asta-flow-page")];
  assert.deepEqual(sections.map(s => s.getAttribute("data-asta-url")),
    [PAGES + "0002-repro.html", PAGES + "0003-gaps.html", PAGES + "0004-review.html"]);
  assert.deepEqual(sections.map(s => s.querySelector(".asta-flow-title a").textContent), ["B", "C", "D"]);
  assert.deepEqual(sections.map(s => s.querySelector(".asta-flow-kicker").textContent),
    ["Next 3 of 5", "Next 4 of 5", "Next 5 of 5"], "the front page comes first in the sidebar");
  assert.equal(sections[0].querySelector("#title-block-header, .asta-flow-content h1.title"), null, "the page's own title block is left out");
  assert.equal(document.querySelector(".asta-flow-end").textContent, "End");

  await b.reachEnd();
  assert.equal(b.fetched.length, 3, "no page is fetched twice");
});

test("on the last workflow page, the end shows at once and nothing is fetched", () => {
  const c = browse(PAGES + "0004-review.html", pageHtml("D", "", FLOW()), SITE);
  assert.ok(c.document.querySelector(".asta-flow-end"));
  assert.deepEqual(c.fetched, []);
});

test("the front page's feed goes on into the workflow pages, skipping other sites and pages listed twice", async () => {
  const extra = [["https://example.org/elsewhere.html", "Elsewhere"], ["./pages/0002-repro.html", "B again"]];
  // The site's root is its front page: at its folder's address, as at index.html.
  for (const at of [ROOT, ROOT + "index.html"]) {
    const site = { ...SITE, [PAGES + "0001-explore.html"]: pageHtml("A", testsPanel("asta-tests-1", [testRow("T1")]), FLOW()) };
    const b = browse(at, pageHtml("Review", "", FLOW("./"), { up: "./", extra }), site);
    for (let i = 0; i < 5; i++) await b.reachEnd();
    assert.deepEqual(b.fetched, ["/_site/pages/0001-explore.html", "/_site/pages/0002-repro.html",
      "/_site/pages/0003-gaps.html", "/_site/pages/0004-review.html"], at);
    const sections = [...b.document.querySelectorAll(".asta-flow-page")];
    assert.deepEqual(sections.map(s => s.querySelector(".asta-flow-kicker").textContent),
      ["Next 2 of 5", "Next 3 of 5", "Next 4 of 5", "Next 5 of 5"]);
    assert.equal(b.document.querySelector(".asta-flow-end").textContent, "End");
    // The workflow pages sit a folder below the front page: their links keep pointing at their files.
    assert.equal(b.document.querySelector('.asta-flow-page[data-asta-url$="0002-repro.html"] a.file').getAttribute("href"),
      "/.asta/flows/0002-b/notes.md");
  }
});

test("a page without the feed's data has no feed", () => {
  const p = browse(PAGES + "0001-explore.html", pageHtml("A", testsPanel("asta-tests-1", [testRow("T1")]), null), SITE);
  assert.equal(p.document.querySelector(".asta-flow"), null);
});

test("panels of several pages in one document: each drawn once, ids kept apart, anchors scoped", async () => {
  const b = browse(PAGES + "0001-explore.html", pageHtml("A", testsPanel("asta-tests-1", [testRow("T1")]), FLOW()), SITE);
  const { document } = b;
  await b.reachEnd();
  await b.reachEnd();
  const tests = [...document.querySelectorAll(".asta-panel.asta-tests")];
  assert.equal(tests.length, 2);
  assert.deepEqual(tests.map(p => p.querySelectorAll("tr.ap-ts-row").length), [1, 2], "each panel draws its own data");
  assert.deepEqual(tests.map(p => p.getAttribute("data-asta-data")), ["asta-tests-1", "asta-f3-asta-tests-1"]);
  assert.equal(document.querySelectorAll('[id="asta-tests-1"]').length, 1, "an appended page's ids are prefixed");
  assert.ok(document.getElementById("asta-f3-tests"), "its headings too");
  const theories = document.querySelector(".asta-flow-page .asta-panel.asta-theories");
  assert.equal(theories.querySelectorAll(".ap-tt tbody tr").length, 2);

  // Drawing again (as for another appended page) leaves drawn panels alone.
  b.AstaPages.init(document);
  assert.equal(tests[1].querySelectorAll("tr.ap-ts-row").length, 2);

  // A relative link in an appended page points where it did on its own page, whatever the address.
  assert.equal(document.querySelector(".asta-flow-page a.file").getAttribute("href"), "/.asta/flows/0002-b/notes.md");

  // #test-T1 on B's address opens B's row only; on A's address, A's row only.
  b.history.replaceState(null, "", PAGES + "0002-repro.html");
  b.visit("#test-T1");
  assert.deepEqual(tests.map(p => p.querySelectorAll("tr.ap-ts-row.ap-open").length), [0, 1]);
  b.history.replaceState(null, "", PAGES + "0001-explore.html");
  b.visit("#test-T1");
  assert.deepEqual(tests.map(p => p.querySelectorAll("tr.ap-ts-row.ap-open").length), [1, 1]);
});

test("a panel of an appended page pushes its own page's address; Back returns to it", async () => {
  const b = browse(PAGES + "0001-explore.html", pageHtml("A", "", FLOW()), SITE);
  await b.reachEnd();
  await b.reachEnd();
  const theories = b.document.querySelector(".asta-flow-page .asta-panel.asta-theories");
  const rows = theories.querySelectorAll(".ap-tt tbody tr");
  // The address is still A's (the page in view): choosing C's theory goes to C's address.
  rows[1].dispatchEvent(new Event("click"));
  assert.equal(b.location.href, PAGES + "0003-gaps.html#theory-2");
  assert.equal(b.AstaPages.hashOf(theories), "#theory-2");
  assert.equal(b.AstaPages.hashOf(b.document.querySelector("#quarto-document-content")), null, "not A's address");
  assert.deepEqual(b.entries, [PAGES + "0001-explore.html", PAGES + "0003-gaps.html#theory-2"]);
  const selected = () => [...rows].map(r => r.classList.contains("ap-selected"));
  assert.deepEqual(selected(), [false, true]);
  b.back();
  assert.equal(b.location.href, PAGES + "0001-explore.html");
  assert.deepEqual(selected(), [false, true], "A's address: C's panel keeps its state");
});

test("a fetch that fails shows a retry, and the feed stops there", async () => {
  const site = { [PAGES + "0002-repro.html"]: null };
  const b = browse(PAGES + "0001-explore.html", pageHtml("A", "", FLOW()), site);
  await b.reachEnd();
  const s = b.document.querySelector(".asta-flow-page");
  assert.match(s.querySelector(".asta-flow-status").textContent, /could not be loaded \(HTTP 404\)/);
  assert.ok(s.querySelector(".asta-flow-retry"));
  assert.equal(b.document.querySelector(".asta-flow-end"), null);
  assert.deepEqual(b.fetched, ["/_site/pages/0002-repro.html"]);
});

test("a reading position in the address is no panel's anchor; a panel's anchor still works", async () => {
  const b = browse(PAGES + "0001-explore.html#flow-at=tests~120",
    pageHtml("A", testsPanel("asta-tests-1", [testRow("T1"), testRow("T2")]), FLOW()), SITE);
  const panel = b.document.querySelector(".asta-panel.asta-tests");
  assert.equal(b.AstaPages.hashOf(panel), "");
  assert.equal(panel.querySelectorAll("tr.ap-ts-row.ap-open").length, 0);
  b.visit("#test-T2");
  assert.deepEqual([...panel.querySelectorAll("tr.ap-ts-row.ap-open")].map(r => r.id), ["test-T2"]);
});

test("a figure shows its copy in the site and links the workspace's file; a large one is a link", () => {
  const F = "../../.asta/flows/0001-demo/04-tests/T1/";
  const row = {
    ...testRow("T1"),
    figures: [
      { name: "fig.png", href: F + "fig.png", src: "../_asta/files/_asta/flows/0001-demo/04-tests/T1/fig.png" },
      { name: "all.png", href: F + "all.png", size: "5.1 MB" },
    ],
  };
  const b = browse(PAGES + "0001-explore.html", pageHtml("A", testsPanel("asta-tests-1", [row]), null), SITE);
  b.visit("#test-T1");
  const figs = [...b.document.querySelectorAll(".ap-ts-fig")];
  assert.equal(figs.length, 2);
  assert.equal(figs[0].getAttribute("href"), F + "fig.png");
  assert.equal(figs[0].querySelector("img").getAttribute("src"), "../_asta/files/_asta/flows/0001-demo/04-tests/T1/fig.png");
  assert.equal(figs[1].getAttribute("href"), F + "all.png");
  assert.equal(figs[1].querySelector("img"), null);
  assert.match(figs[1].textContent, /5\.1 MB, too large to show here/);
});

test("a reading position puts a panel's own scrolling list back where it was", async () => {
  const b = browse(PAGES + "0001-explore.html#flow-at=tests~0~0:120",
    pageHtml("A", testsPanel("asta-tests-1", [testRow("T1"), testRow("T2")]), FLOW()), SITE);
  await new Promise(r => setTimeout(r, 5));
  assert.equal(b.document.querySelector(".ap-ts-scroll").scrollTop, 120);
});

test("scrolling a panel's own list is kept in the address before a click can leave the page", () => {
  const b = browse(PAGES + "0001-explore.html",
    pageHtml("A", testsPanel("asta-tests-1", [testRow("T1"), testRow("T2")]), FLOW()), SITE);
  const { document, window } = b;
  // The window is inside the Tests section, 40 px below its top.
  const proto = Object.getPrototypeOf(document.getElementById("tests"));
  const rect = proto.getBoundingClientRect;
  proto.getBoundingClientRect = function () { return { top: this.id === "tests" ? -40 : 500 }; };
  try {
    const list = document.querySelector(".ap-ts-scroll");
    list.scrollTop = 850;
    // A list's scroll event does not bubble; the feed listens in the capture phase, which
    // linkedom does not run, so the test lets it bubble to the same listener.
    list.dispatchEvent(new Event("scroll", { bubbles: true }));
    assert.equal(b.location.hash, "", "not yet: written once the list stops");
    (window.__listeners?.pointerdown ?? []).forEach(fn => fn());
    assert.equal(b.location.hash, "#flow-at=tests~40~0:850");
  } finally {
    proto.getBoundingClientRect = rect;
  }
});

// What asta-pages.lua lists of each page's sections: its level-2 headings and their ids.
const SECTIONS = (up = "../") => ({
  format: "asta-pages/sections@1", site: up,
  pages: {
    "index.html": [{ id: "mission", title: "Mission" }, { id: "found", title: "Findings" }],
    "pages/0001-explore.html": [{ id: "tests", title: "Tests" }],
    "pages/0002-repro.html": [{ id: "tests", title: "Tests" }, { id: "résumé-état", title: "Résumé, état" }],
  },
});

test("each page's sections are listed under its sidebar link: this page's open, the others shut", () => {
  const toc = '<li><a href="#tests" class="nav-link">Tests</a></li>';
  const b = browse(PAGES + "0001-explore.html", pageHtml("A", "", null, { sections: SECTIONS(), toc }), SITE);
  const { document } = b;
  const lists = [...document.querySelectorAll("#quarto-sidebar ul.asta-sections")];
  assert.equal(lists.length, 3, "only the pages with sections get a list");
  const under = ul => ul.closest("li").querySelector(".sidebar-link").textContent;
  assert.deepEqual(lists.map(under), ["Review", "A", "B"]);
  assert.deepEqual(lists.map(ul => [...ul.querySelectorAll("a")].map(a => [a.textContent, a.getAttribute("href")])), [
    [["Mission", "/_site/index.html#mission"], ["Findings", "/_site/index.html#found"]],
    [["Tests", "/_site/pages/0001-explore.html#tests"]],
    [["Tests", "/_site/pages/0002-repro.html#tests"], ["Résumé, état", "/_site/pages/0002-repro.html#r%C3%A9sum%C3%A9-%C3%A9tat"]],
  ]);
  const toggles = lists.map(ul => ul.closest("li").querySelector(".sidebar-item-toggle"));
  assert.deepEqual(lists.map(ul => ul.classList.contains("show")), [false, true, false]);
  assert.deepEqual(toggles.map(t => t.getAttribute("aria-expanded")), ["false", "true", "false"]);
  assert.ok(toggles[0].querySelector("i.bi-chevron-right"), "Quarto's chevron");
  assert.equal(toggles[0].getAttribute("aria-controls"), lists[0].id);
  assert.ok(lists[1].querySelector("a.active"), "this page's section in view is marked");
  assert.ok(document.getElementById("TOC").classList.contains("asta-toc-same"), "'On this page' lists the same: hidden");
  const deeper = browse(PAGES + "0001-explore.html", pageHtml("A", "", null, {
    sections: SECTIONS(), toc: '<li><a href="#tests">Tests</a><ul><li><a href="#t1">T1</a></li></ul></li>' }), SITE);
  assert.equal(deeper.document.getElementById("TOC").classList.contains("asta-toc-same"), false, "with subsections it stays");

  // The chevron opens and shuts a page's list.
  toggles[0].dispatchEvent(new Event("click"));
  assert.equal(lists[0].classList.contains("show"), true);
  toggles[0].dispatchEvent(new Event("click"));
  assert.equal(lists[0].classList.contains("show"), false);
});

test("in the feed the sections follow the page in view, and a click on an appended page's section scrolls there", async () => {
  // Quarto's script makes "On this page"'s links full addresses.
  const toc = `<li><a href="${PAGES}0001-explore.html#tests">Tests</a></li>`;
  const b = browse(PAGES + "0001-explore.html", pageHtml("A", "", FLOW(), { sections: SECTIONS(), toc }), SITE);
  const { document, window } = b;
  const tocHidden = () => document.getElementById("TOC").classList.contains("asta-toc-same");
  assert.ok(tocHidden(), "A's 'On this page' repeats A's sections, in another form: hidden");
  await b.reachEnd();
  const appended = document.querySelector(".asta-flow-page");
  // B's page is in view, its Résumé section above the line.
  const proto = Object.getPrototypeOf(appended);
  const rect = proto.getBoundingClientRect;
  proto.getBoundingClientRect = function () {
    if (this === appended) return { top: 50 };
    if (this.id === "asta-f3-résumé-état") return { top: 100 };
    return { top: this.id === "asta-f3-tests" ? -300 : 900 };
  };
  const scrolled = [];
  proto.scrollIntoView = function () { scrolled.push(this.id); };
  try {
    (window.__listeners.scroll ?? []).forEach(fn => fn());
    await new Promise(r => setTimeout(r, 5));
    assert.equal(b.location.href, PAGES + "0002-repro.html", "the address is B's");
    const lists = [...document.querySelectorAll("#quarto-sidebar ul.asta-sections")];
    assert.deepEqual(lists.map(ul => ul.classList.contains("show")), [false, false, true], "B's list opens, A's shuts");
    assert.deepEqual([...document.querySelectorAll("#quarto-sidebar a.asta-section-link.active")].map(a => a.textContent), ["Résumé, état"]);
    assert.equal(document.querySelector("#quarto-sidebar a.sidebar-link.active:not(.asta-section-link)").textContent, "B");
    assert.equal(document.querySelector("#TOC a").textContent, "Tests", "B's own list");
    assert.ok(tocHidden(), "B's list repeats B's sections: hidden");

    // B's Tests is on this document, under the id the feed gave it.
    const ev = new Event("click", { bubbles: true, cancelable: true });
    lists[2].querySelector("a").dispatchEvent(ev);
    assert.equal(ev.defaultPrevented, true);
    assert.deepEqual(scrolled, ["asta-f3-tests"]);
    assert.equal(b.location.href, PAGES + "0002-repro.html#tests");
    // The jump's own scrolling leaves the address naming the section...
    const fire = type => (window.__listeners[type] ?? []).forEach(fn => fn());
    fire("scroll");
    await new Promise(r => setTimeout(r, 5));
    fire("pointerdown");
    assert.equal(b.location.href, PAGES + "0002-repro.html#tests", "the section's id, not a reading position");
    // ...until the reader scrolls on.
    fire("wheel");
    fire("scroll");
    await new Promise(r => setTimeout(r, 5));
    fire("pointerdown");
    assert.equal(b.location.href, PAGES + "0002-repro.html#flow-at=tests~300");
    // A section of a page not loaded yet is an ordinary link.
    const other = new Event("click", { bubbles: true, cancelable: true });
    lists[0].querySelector("a").dispatchEvent(other);
    assert.equal(other.defaultPrevented, false);
  } finally {
    proto.getBoundingClientRect = rect;
    delete proto.scrollIntoView;
  }
});

test("a page opened at a section keeps the section's id in the address until the reader scrolls", async () => {
  const b = browse(PAGES + "0001-explore.html#tests", pageHtml("A", "", FLOW()), SITE);
  const { document, window } = b;
  const fire = type => (window.__listeners[type] ?? []).forEach(fn => fn());
  const proto = Object.getPrototypeOf(document.getElementById("tests"));
  const rect = proto.getBoundingClientRect;
  // The window is 40 px into the Tests section (the browser's jump, the page settling).
  proto.getBoundingClientRect = function () { return { top: this.id === "tests" ? -40 : 500 }; };
  try {
    const settle = async () => { fire("scroll"); await new Promise(r => setTimeout(r, 5)); fire("pointerdown"); };
    await settle();
    assert.equal(b.location.href, PAGES + "0001-explore.html#tests", "opened at #tests: kept");
    fire("wheel");
    await settle();
    assert.equal(b.location.href, PAGES + "0001-explore.html#flow-at=tests~40", "the reader scrolled: their place");
    // Going to a section again (a link to #tests) names it again.
    b.visit("#tests");
    await settle();
    assert.equal(b.location.href, PAGES + "0001-explore.html#tests");
  } finally {
    proto.getBoundingClientRect = rect;
  }
});
