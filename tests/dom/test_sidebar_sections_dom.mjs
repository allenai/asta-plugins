import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

import { Event, parseHTML } from "linkedom";

const dir = new URL("../../plugins/asta-tools/skills/workspace/assets/_extensions/asta-templates/", import.meta.url);
const CORE = fs.readFileSync(new URL("asta-templates.js", dir), "utf8");

const ORIGIN = "http://site.test";
const PAGES = `${ORIGIN}/_site/pages/`;

// The scaffold's sidebar: the front page, then the workflow pages flat, by file name (run order),
// on a page at `up` from the site's root ("../" for a workflow page). Quarto's script links the
// front page as the site's folder.
const sidebarItem = (href, text) => `<li class="sidebar-item"><div class="sidebar-item-container"><a href="${href}" class="sidebar-item-text sidebar-link">${text}</a></div></li>`;
const sidebar = (up = "../") => `<nav id="quarto-sidebar"><ul>` + sidebarItem(up, "Review") +
  [["0001-explore.html", "A"], ["0002-repro.html", "B"], ["0003-gaps.html", "C"]]
    .map(([f, t]) => sidebarItem(`${up}pages/${f}`, t)).join("") + "</ul></nav>";

// What asta-templates.lua lists of each page's sections: its level-2 headings and their ids.
const SECTIONS = (up = "../") => ({
  format: "asta-templates/sections@1", site: up,
  pages: {
    "index.html": [{ id: "mission", title: "Mission" }, { id: "found", title: "Findings" }],
    "pages/0001-explore.html": [{ id: "tests", title: "Tests" }],
    "pages/0002-repro.html": [{ id: "tests", title: "Tests" }, { id: "résumé-état", title: "Résumé, état" }],
  },
});

// A rendered workflow page: Quarto's title block, a step's heading, and the sidebar's data.
function pageHtml(title, { toc = "", sections = SECTIONS() } = {}) {
  return `<!doctype html><html><head><title>${title} – Demo</title></head><body>` + sidebar() +
    (toc ? `<nav id="TOC" role="doc-toc"><ul>${toc}</ul></nav>` : "") +
    `<main class="content" id="quarto-document-content"><header id="title-block-header"><h1 class="title">${title}</h1></header>` +
    `<section id="tests" class="level2"><h2>Tests</h2></section></main>` +
    (sections ? `<script type="application/json" id="asta-sections">${JSON.stringify(sections)}</script>` : "") +
    "</body></html>";
}

// A browser for the page at `url`: its address and history, and the core script.
function browse(url, html) {
  const { document } = parseHTML(html);
  const listeners = {};
  let href = url;
  const location = {
    get href() { return href; },
    get hash() { const i = href.indexOf("#"); return i < 0 || i === href.length - 1 ? "" : href.slice(i); },
    get origin() { return ORIGIN; },
  };
  const entries = [href];
  const history = { state: null, pushState: (_, __, u) => { href = new URL(u, href).href; entries.push(href); }, replaceState() {} };
  const window = { addEventListener: (type, fn) => (listeners[type] ??= []).push(fn), innerHeight: 800, scrollY: 0 };
  vm.runInNewContext(CORE, { window, document, location, history, URL, console, setTimeout, clearTimeout });
  return { document, window, location, entries };
}

test("each page's sections are listed under its sidebar link: this page's open, the others shut", () => {
  const toc = '<li><a href="#tests" class="nav-link">Tests</a></li>';
  const b = browse(PAGES + "0001-explore.html", pageHtml("A", { toc }));
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
  const deeper = browse(PAGES + "0001-explore.html", pageHtml("A", {
    toc: '<li><a href="#tests">Tests</a><ul><li><a href="#t1">T1</a></li></ul></li>' }));
  assert.equal(deeper.document.getElementById("TOC").classList.contains("asta-toc-same"), false, "with subsections it stays");
  // Quarto's script makes "On this page"'s links full addresses: still the same list.
  const full = browse(PAGES + "0001-explore.html", pageHtml("A", { toc: `<li><a href="${PAGES}0001-explore.html#tests">Tests</a></li>` }));
  assert.ok(full.document.getElementById("TOC").classList.contains("asta-toc-same"));

  // The chevron opens and shuts a page's list.
  toggles[0].dispatchEvent(new Event("click"));
  assert.equal(lists[0].classList.contains("show"), true);
  toggles[0].dispatchEvent(new Event("click"));
  assert.equal(lists[0].classList.contains("show"), false);
});

test("a click on this page's section scrolls there; another page's section is an ordinary link", () => {
  const b = browse(PAGES + "0002-repro.html", pageHtml("B"));
  const { document } = b;
  const tests = document.getElementById("tests");
  const proto = Object.getPrototypeOf(tests);
  const scrolled = [];
  proto.scrollIntoView = function () { scrolled.push(this.id); };
  try {
    const lists = [...document.querySelectorAll("#quarto-sidebar ul.asta-sections")];
    const ev = new Event("click", { bubbles: true, cancelable: true });
    lists[2].querySelector("a").dispatchEvent(ev);
    assert.equal(ev.defaultPrevented, true);
    assert.deepEqual(scrolled, ["tests"]);
    assert.equal(b.location.href, PAGES + "0002-repro.html#tests", "the address names the section");
    const other = new Event("click", { bubbles: true, cancelable: true });
    lists[0].querySelector("a").dispatchEvent(other);
    assert.equal(other.defaultPrevented, false);
  } finally {
    delete proto.scrollIntoView;
  }
});

test("a page without the sections' data leaves the sidebar as Quarto drew it", () => {
  const b = browse(PAGES + "0001-explore.html", pageHtml("A", { sections: null }));
  assert.equal(b.document.querySelector("#quarto-sidebar ul.asta-sections"), null);
});
