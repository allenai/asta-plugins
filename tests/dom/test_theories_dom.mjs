import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

import { parseHTML } from "linkedom";

const code = fs.readFileSync(
  new URL("../../plugins/asta-tools/skills/workspace/assets/_extensions/asta-templates/theories.js", import.meta.url),
  "utf8",
);

const theory = (id, name, query) => ({ id, name, query, statements: [], supporting: 0, conflicting: 0 });

// The page the asta-theories shortcode writes: the panel, then one script element per data file.
function runPage(files, { hash = "", names, papers } = {}) {
  const scripts = files.map(([src, data], i) =>
    `<script type="application/json" class="asta-theories-data"${i === 0 ? ' id="asta-theories-data"' : ""}` +
    ` data-asta-source="${src}">${JSON.stringify(data)}</script>`).join("");
  const namesAttr = names ? ` data-asta-names='${JSON.stringify(names)}'` : "";
  const papersAttr = papers ? ` data-asta-papers="${papers}"` : "";
  const { document, Event } = parseHTML(
    `<!doctype html><html><body><div class="asta-panel asta-theories"${namesAttr}${papersAttr}></div>${scripts}</body></html>`);
  const location = { hash };
  const listeners = {};
  // The page's window, as far as theories.js uses it (linkedom's own refuses new properties).
  const window = { addEventListener: (type, fn) => (listeners[type] ??= []).push(fn) };
  // The browser's history for this page: every entry's fragment, the current one last.
  const entries = [hash];
  vm.runInNewContext(code, {
    window,
    document,
    location,
    history: {
      replaceState: (_, __, url) => { location.hash = url; entries[entries.length - 1] = url; },
      pushState: (_, __, url) => { location.hash = url; entries.push(url); },
    },
  });
  const dispatch = type => (listeners[type] ?? []).forEach(fn => fn());
  const go = h => { location.hash = h; dispatch("hashchange"); };
  // Back, as a browser does it: popstate, then hashchange (the fragment differs).
  const back = () => { entries.pop(); location.hash = entries[entries.length - 1]; dispatch("popstate"); dispatch("hashchange"); };
  const panel = document.querySelector(".asta-theories");
  const fire = (el, type, key) => { const ev = new Event(type); if (key) ev.key = key; el.dispatchEvent(ev); };
  return { document, panel, location, go, back, entries, fire };
}

const QUERY_A = "Build theories, expressed as IF ... THEN laws, about the following question: why do some children not respond?";
const QUERY_B = "Build theories, expressed as IF ... THEN laws, about the following question: what does household serology say?";

test("one query: shown above the table, with no tabs", () => {
  const { panel } = runPage([["data/theorizer.json", {
    theories: [theory("theory-1", "One", QUERY_A), theory("theory-2", "Two", "  " + QUERY_A.replace(/ /g, "\n  ") + " ")],
  }]]);
  assert.equal(panel.querySelectorAll(".ap-qtab").length, 0);
  assert.equal(panel.querySelectorAll(".ap-query").length, 1);
  assert.equal(panel.querySelector(".ap-query figcaption").textContent, "Theory query");
  assert.match(panel.querySelector(".ap-query blockquote").textContent, /why do some children not respond/);
  assert.equal(panel.querySelectorAll(".ap-tt tbody tr").length, 2, "spacing does not split a query");
  assert.ok(panel.innerHTML.indexOf("ap-query") < panel.innerHTML.indexOf("ap-tt"), "the query comes before the table");
});

test("several files and queries: deduplicated, one tab per query, remembered in the hash", () => {
  const first = { theories: [theory("theory-1", "One", QUERY_A), theory("theory-2", "Two", QUERY_A)] };
  const second = {
    theories: [theory("theory-2", "Two", QUERY_A), theory("theory-1", "Other one", QUERY_B), theory("theory-3", "Three", QUERY_B)],
  };
  const { panel, location, go, fire } = runPage([["data/theorizer.json", first], ["data/theorizer-v2.json", second]]);
  const tabs = [...panel.querySelectorAll(".ap-qtab")];
  assert.equal(tabs.length, 2);
  assert.match(tabs[0].textContent, /^Query 1 · 2 theories/);
  assert.match(tabs[1].textContent, /^Query 2 · 2 theories/);
  assert.match(tabs[1].querySelector(".ap-qtab-excerpt").textContent, /^what does household serology say/,
    "the excerpt skips the opening the queries share");
  const panels = [...panel.querySelectorAll(".ap-qpanel")];
  assert.deepEqual(panels.map(p => p.hidden), [false, true]);
  assert.deepEqual(panels.map(p => p.querySelectorAll(".ap-tt tbody tr").length), [2, 2], "theory-2 is shown once");
  assert.match(panels[1].querySelector(".ap-query blockquote").textContent, /household serology/);

  fire(tabs[1], "click");
  assert.equal(location.hash, "#query-2");
  assert.deepEqual(panels.map(p => p.hidden), [true, false]);
  assert.equal(tabs[1].getAttribute("aria-selected"), "true");
  assert.equal(tabs[1].getAttribute("tabindex"), "0");
  assert.equal(tabs[0].getAttribute("tabindex"), "-1");
  assert.match(panels[1].querySelector(".ap-theory h2").textContent, /Other one/);

  go("#query-1");
  assert.deepEqual(panels.map(p => p.hidden), [false, true]);
  // The second file's theory-1 is a different theory: it is anchored under its file's name.
  go("#theorizer-v2/theory-1");
  assert.deepEqual(panels.map(p => p.hidden), [true, false]);
  assert.equal(panels[1].querySelector(".ap-theory").id, "theorizer-v2/theory-1");
  go("#theory-3");
  assert.match(panels[1].querySelector(".ap-theory h2").textContent, /Three/);
});

test("arrow keys move between query tabs", () => {
  const { panel, location, fire } = runPage([["a.json", { theories: [theory("t1", "One", QUERY_A), theory("t2", "Two", QUERY_B)] }]],
    { names: ["Original", "Revised"] });
  const tabs = [...panel.querySelectorAll(".ap-qtab")];
  assert.match(tabs[0].textContent, /^Original · 1 theory/);
  const key = (el, k) => fire(el, "keydown", k);
  key(tabs[0], "ArrowRight");
  assert.equal(tabs[1].getAttribute("aria-selected"), "true");
  assert.equal(location.hash, "#query-2");
  key(tabs[1], "ArrowRight");
  assert.equal(tabs[0].getAttribute("aria-selected"), "true", "wraps around");
  key(tabs[0], "End");
  assert.equal(tabs[1].getAttribute("aria-selected"), "true");
});

test("choosing a theory or a tab is a step in the history; Back returns to the list and the tab before", () => {
  const { panel, location, entries, back, fire } = runPage([["a.json", {
    theories: [theory("theory-1", "One", QUERY_A), theory("theory-2", "Two", QUERY_A), theory("theory-3", "Three", QUERY_B)],
  }]]);
  const tabs = [...panel.querySelectorAll(".ap-qtab")];
  const panels = [...panel.querySelectorAll(".ap-qpanel")];
  const shownTheory = k => panels[k].querySelector(".ap-theory h2").textContent;
  assert.match(shownTheory(0), /^One/);

  fire(panels[0].querySelectorAll(".ap-tt tbody tr")[1], "click");
  assert.match(shownTheory(0), /^Two/);
  fire(tabs[0], "click");   // the tab already shown: no step
  fire(tabs[1], "click");
  fire(panels[1].querySelectorAll(".ap-tt tbody tr")[0], "click");   // the theory already shown: a step to its anchor
  assert.deepEqual(entries, ["", "#theory-2", "#query-2", "#theory-3"]);

  back();
  assert.equal(location.hash, "#query-2");
  assert.deepEqual(panels.map(p => p.hidden), [true, false]);
  back();
  assert.deepEqual(panels.map(p => p.hidden), [false, true], "Back from a tab returns to the tab before");
  assert.match(shownTheory(0), /^Two/);
  back();
  assert.equal(location.hash, "");
  assert.match(shownTheory(0), /^One/, "Back to the list shows the page as it first opened");
  assert.equal(tabs[0].getAttribute("aria-selected"), "true");
});

test("paper titles link to their entry on the papers page; a copy shown once links to its card", () => {
  const data = {
    papers: [
      { key: "s2-1", corpusId: "123", title: "Store paper" },
      { key: "doc a", title: "Hand-collected", duplicates: [{ key: "doc a copy" }] },
    ],
    theories: [{
      ...theory("theory-1", "One", QUERY_A),
      statements: [{ name: "S", statement: "x", evidence: [
        { text: "e1", paper: "s2-1" }, { text: "e2", paper: "doc a" }, { text: "e3", paper: "doc a copy" }] }],
      papers: ["s2-1", "doc a", "doc a copy"],
    }],
  };
  const titles = page => [...page.panel.querySelectorAll(".ap-ev-paper, .ap-paper-title")]
    .map(el => [el.tagName.toLowerCase(), el.getAttribute("href"), el.getAttribute("target"), el.textContent]);
  const store = ["a", "papers.html#paper-123", null, "Store paper"];
  const hand = ["a", "papers.html#paper-doc%20a", null, "Hand-collected"];
  // Statements tab (three pieces of evidence), then Referenced papers (the copy is the same card).
  assert.deepEqual(titles(runPage([["a.json", data]], { papers: "papers.html" })), [store, hand, hand, store, hand]);
  // No papers page named: the run's literature page.
  assert.deepEqual(titles(runPage([["a.json", data]]))[0], ["a", "literature.html#paper-123", null, "Store paper"]);
  assert.ok(!/semanticscholar/.test(runPage([["a.json", data]]).panel.innerHTML), "never links outwards");
});

test("a hash naming a query opens its tab on load", () => {
  const { panel } = runPage([["a.json", { theories: [theory("t1", "One", QUERY_A), theory("t2", "Two", QUERY_B)] }]],
    { hash: "#query-2" });
  assert.deepEqual([...panel.querySelectorAll(".ap-qpanel")].map(p => p.hidden), [true, false]);
});

test("a hash naming a paper opens the first theory that references it, on its Referenced papers tab", () => {
  const data = {
    papers: [
      { key: "paper-aa", corpusId: "123", title: "Store paper" },
      { key: "paper-bb", corpusId: "456", title: "Other paper", duplicates: [{ key: "paper-cc", corpusId: "789" }] },
    ],
    theories: [
      { ...theory("theory-1", "One", QUERY_A), papers: ["paper-aa"] },
      { ...theory("theory-2", "Two", QUERY_A), papers: ["paper-aa", "paper-bb"] },
    ],
  };
  const { panel, go } = runPage([["a.json", data]], { hash: "#paper-456" });
  const shown = () => panel.querySelector(".ap-theory h2").textContent;
  const tab = () => panel.querySelector('.ap-tab[aria-selected="true"]').getAttribute("data-tab");
  assert.match(shown(), /^Two/);
  assert.equal(tab(), "papers");
  assert.equal(panel.querySelector(".ap-paper.ap-target").id, "paper-456");
  go("#paper-123");
  assert.match(shown(), /^One/, "the first theory that references it");
  assert.equal(panel.querySelector(".ap-paper.ap-target").id, "paper-123");
  // A copy shown once is found on the card that lists it.
  go("#paper-789");
  assert.match(shown(), /^Two/);
  assert.equal(panel.querySelector(".ap-paper.ap-target").id, "paper-456");
});
