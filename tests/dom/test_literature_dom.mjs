import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

import { parseHTML } from "linkedom";

const code = fs.readFileSync(
  new URL("../../plugins/asta-tools/skills/workspace/assets/_extensions/asta-templates/literature.js", import.meta.url),
  "utf8",
);

// The page the asta-literature shortcode writes, opened at `hash` (a theory's evidence link).
function runPage(data, hash) {
  const { document, Event } = parseHTML(
    `<!doctype html><html><body><div class="asta-panel asta-literature"></div>` +
    `<script type="application/json" id="asta-literature-data">${JSON.stringify(data)}</script></body></html>`);
  const listeners = {};
  const window = { addEventListener: (type, fn) => (listeners[type] ??= []).push(fn) };
  const location = { hash };
  const scrolled = [];
  document.defaultView.HTMLElement.prototype.scrollIntoView = function () { scrolled.push(this.id); };
  vm.runInNewContext(code, { window, document, location });
  const go = h => { location.hash = h; (listeners.hashchange ?? []).forEach(fn => fn()); };
  return { document, go, scrolled, Event };
}

const DATA = {
  papers: [
    { key: "11", corpusId: "11", title: "Store paper", year: 2020 },
    { key: "hist:a", corpusId: null, title: "Hand-collected", year: 1990, duplicates: [{ key: "hist:a copy", corpusId: null }] },
  ],
};
const marked = document => [...document.querySelectorAll(".ap-paper.ap-target")].map(el => el.id);

test("a #paper- link marks its card and scrolls to it", () => {
  const { document, scrolled } = runPage(DATA, "#paper-hist%3Aa");
  assert.deepEqual(marked(document), ["paper-hist:a"]);
  assert.deepEqual(scrolled, ["paper-hist:a"]);
});

test("a copy shown once goes to the card that lists it", () => {
  const { document } = runPage(DATA, "#paper-" + encodeURIComponent("hist:a copy"));
  assert.deepEqual(marked(document), ["paper-hist:a"]);
});

test("a filter that hides the paper is cleared", () => {
  const { document, go, Event } = runPage(DATA, "");
  const q = document.querySelector('input[type="search"]');
  q.value = "store";
  q.dispatchEvent(new Event("input"));
  assert.equal(document.getElementById("paper-hist:a"), null);
  go("#paper-hist%3Aa");
  assert.deepEqual(marked(document), ["paper-hist:a"]);
  assert.equal(q.value, "");
});

test("the year facet lists every decade, newest first, unknown years last", () => {
  const papers = [1948, 1955, 1963, 1977, 1984, 1991, 2003, 2012, 2021, 2025, null]
    .map((year, i) => ({ key: String(i), corpusId: String(i), title: "P" + i, year }));
  const { document } = runPage({ papers }, "");
  const decades = [...document.querySelectorAll('input[data-facet="year"]')].map(el => el.value);
  assert.deepEqual(decades, ["2020s", "2010s", "2000s", "1990s", "1980s", "1970s", "1960s", "1950s", "1940s", "Year unknown"]);
});
