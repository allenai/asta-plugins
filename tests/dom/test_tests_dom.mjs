import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

import { parseHTML } from "linkedom";

const dir = new URL("../../plugins/asta-tools/skills/workspace/assets/_extensions/asta-templates/", import.meta.url);
const testsJs = fs.readFileSync(new URL("tests.js", dir), "utf8");
const theoriesJs = fs.readFileSync(new URL("theories.js", dir), "utf8");

// Tests in the shapes asta-templates.lua embeds: links are already relative to the rendered page.
const F = "../../.asta/flows/0001-demo/04-tests/";
const TESTS = [
  { id: "T1", href: F + "T1/", design: F + "T1/design.md", code: F + "T1/test.py", codeName: "test.py",
    summaryHref: F + "T1/result_summary.json", summaryName: "result_summary.json",
    figures: [{ name: "fig.png", href: F + "T1/fig.png" }],
    index: { test_id: "T1", theory_name: "Theory one", kind: "supporting" },
    summary: { ran: true, meets_threshold: true, effect: 0.25, effect_name: "mean difference", p: 0.0004, n_animals: 6 } },
  { id: "T2", href: F + "T2/", index: { test_id: "T2", theory_name: "Theory  one" },
    summary: { meets_threshold: { A: true, B: false, rule: "both regions" }, effect: { A: 0.1, B: -0.2 },
      p: { A: { p: 0.02, W: 14 }, B: { p: 0.4, W: 3 } }, n_animals: { A: 5, B: 4 } } },
  { id: "T3", href: F + "T3/", summary: { ran: false, status: "no data" } },
  { id: "T4", href: F + "T4/", design: F + "T4/design.md", heading: "Committed test T4" },
  { id: "T5", missing: true, index: { test_id: "T5", theory_name: "Theory two" } },
  { id: "T6", href: F + "T6/", summary: { verdict: "partly supported", status: "one region" } },
  { id: "node_2_1", href: F + "node_2_1/", hypothesis: "Something changes after a switch.",
    summary: { subject_level_tests: [{ name: "first", n_mice: 5 }, { name: "second", n_mice: 6, effect: 1.5, p: 0.03 }] } },
];

function page(body, { hash = "" } = {}) {
  const { document, Event } = parseHTML(`<!doctype html><html><body>${body}</body></html>`);
  const location = { hash };
  const listeners = {};
  const window = { addEventListener: (type, fn) => (listeners[type] ??= []).push(fn) };
  const ctx = { window, document, location, history: { pushState() {}, replaceState() {} } };
  vm.runInNewContext(testsJs, ctx);
  const go = h => { location.hash = h; (listeners.hashchange ?? []).forEach(fn => fn()); };
  return { document, window, ctx, Event, go };
}

const panel = (tests, others = []) =>
  `<div class="asta-panel asta-tests" data-asta-data="d1"></div>` +
  `<script type="application/json" class="asta-tests-data" id="d1">${JSON.stringify({ tests, others })}</script>`;

test("verdicts: explicit, not run, met, per region, undecided, running, not started", () => {
  const { window } = page("");
  const v = t => window.AstaTemplates.testsLib.verdict(t);
  assert.deepEqual(TESTS.map(t => [v(t).key, v(t).label]), [
    ["met", "met"],
    ["partial", "met in 1 of 2"],
    ["notrun", "not run"],
    ["running", "running"],
    ["notstarted", "not started"],
    ["partial", "partly supported"],
    ["undecided", "undecided"],
  ]);
  assert.equal(v({ id: "x", summary: { meets_threshold: false } }).key, "notmet");
  assert.equal(v({ id: "x", summary: { meets_threshold: { A: true, B: true } } }).label, "met in 2 of 2");
  assert.equal(v({ id: "x", summary: { verdict: "rejected (agrees with the source)" } }).key, "notmet");
  assert.equal(v({ id: "x", summary: { status: "not decided (power)" } }).note, "not decided (power)");
});

test("the table: one row per test, its numbers, links and the verdict filter", () => {
  const { document } = page(panel(TESTS, [{ name: "seed.json", href: F + "seed.json", size: "2 B" }]));
  const root = document.querySelector(".asta-tests");
  const rows = [...root.querySelectorAll("tr.ap-ts-row")];
  assert.deepEqual(rows.map(r => r.id), TESTS.map(t => "test-" + t.id));
  const cells = rows[0].querySelectorAll("td");
  assert.match(cells[1].textContent, /Theory one/);
  assert.match(cells[1].textContent, /supporting/);
  assert.equal(cells[2].textContent, "met");
  assert.match(cells[3].textContent, /^0\.25/);
  assert.equal(cells[4].textContent, "<0.001");
  assert.equal(cells[5].textContent, "6");
  assert.deepEqual([...cells[6].querySelectorAll("a")].map(a => [a.textContent, a.getAttribute("href")]), [
    ["design", F + "T1/design.md"], ["code", F + "T1/test.py"], ["summary", F + "T1/result_summary.json"],
  ]);
  // A per-region p is shown as its range of p values (the test statistic W is left out).
  assert.equal(rows[1].querySelectorAll("td")[4].textContent, "0.02–0.4");
  assert.equal(rows[1].querySelectorAll("td")[5].textContent, "4–5");
  assert.match(rows[1].querySelector(".ap-ts-parts").textContent, /A ✓ B ✗/);
  // What a test tests, without an index: its hypothesis, else its design's heading.
  assert.match(rows[3].querySelectorAll("td")[1].textContent, /Committed test T4/);
  assert.match(rows[6].querySelectorAll("td")[1].textContent, /Something changes after a switch/);
  assert.match(rows[6].querySelectorAll("td")[3].textContent, /1\.5.*second.*\+1 more test/s);
  assert.match(rows[4].querySelectorAll("td")[6].textContent, /no folder/);
  assert.match(root.querySelector(".ap-ts-others").innerHTML, /seed\.json/);

});

test("filtering by verdict, sorting by p, and opening a row", () => {
  const { document, Event } = page(panel(TESTS));
  const root = document.querySelector(".asta-tests");
  const click = el => el.dispatchEvent(new Event("click", { bubbles: true }));
  click(root.querySelector('.ap-ts-filter[data-only="partial"]'));
  assert.deepEqual([...root.querySelectorAll("tr.ap-ts-row")].map(r => r.id), ["test-T2", "test-T6"]);
  click(root.querySelector('.ap-ts-filter[data-only=""]'));
  click(root.querySelector('[data-sort="p"]'));
  assert.deepEqual([...root.querySelectorAll("tr.ap-ts-row")].map(r => r.id).slice(0, 3), ["test-T1", "test-T2", "test-node_2_1"]);
  click(root.querySelector("#test-T1 td"));
  const detail = root.querySelector("tr.ap-ts-detail");
  assert.ok(detail, "the row opens");
  assert.match(detail.textContent, /mean difference/);
  assert.equal(detail.querySelector(".ap-ts-fig img").getAttribute("src"), F + "T1/fig.png");
  assert.ok([...detail.querySelectorAll("a")].some(a => a.getAttribute("href") === F + "T1/"), "links the folder");
});

test("#test-<id> opens that row", () => {
  const { document } = page(panel(TESTS), { hash: "#test-T3" });
  const open = document.querySelector("tr.ap-ts-row.ap-open");
  assert.equal(open.id, "test-T3");
  assert.match(document.querySelector("tr.ap-ts-detail").textContent, /no data/);
});

test("a figure shows its copy in the site and links the workspace's file; a large one is a link", () => {
  const row = {
    id: "T1", href: F + "T1/", summary: { meets_threshold: true },
    figures: [
      { name: "fig.png", href: F + "T1/fig.png", src: "../_asta/files/_asta/flows/0001-demo/04-tests/T1/fig.png" },
      { name: "all.png", href: F + "T1/all.png", size: "5.1 MB" },
    ],
  };
  const { document, go } = page(panel([row]));
  go("#test-T1");
  const figs = [...document.querySelectorAll(".ap-ts-fig")];
  assert.equal(figs.length, 2);
  assert.equal(figs[0].getAttribute("href"), F + "T1/fig.png");
  assert.equal(figs[0].querySelector("img").getAttribute("src"), "../_asta/files/_asta/flows/0001-demo/04-tests/T1/fig.png");
  assert.equal(figs[1].getAttribute("href"), F + "T1/all.png");
  assert.equal(figs[1].querySelector("img"), null);
  assert.match(figs[1].textContent, /5\.1 MB, too large to show here/);
});

test("a theory page with tests: a verdict column and a Tests tab, matched by name", () => {
  const data = { theories: [
    { id: "theory-1", name: "Theory one", query: "Q", statements: [] },
    { id: "theory-2", name: "Theory two", query: "Q", statements: [] },
    { id: "theory-3", name: "Theory three", query: "Q", statements: [] },
  ] };
  const extra = { id: "T9", href: F + "T9/", index: { test_id: "T9", theory_name: "Not here" }, summary: {} };
  const { document, ctx } = page(
    `<div class="asta-panel asta-theories"></div>` +
    `<script type="application/json" class="asta-theories-data" id="asta-theories-data">${JSON.stringify(data)}</script>` +
    `<script type="application/json" class="asta-theories-tests">${JSON.stringify({ tests: [...TESTS, extra] })}</script>`);
  vm.runInNewContext(theoriesJs, ctx);
  const root = document.querySelector(".asta-theories");
  const cells = [...root.querySelectorAll("td.ap-tt-tests")].map(td => td.textContent);
  assert.deepEqual(cells, ["1 of 2 met, 1 partly", "0 of 1 met", "—"]);
  const tab = root.querySelector('.ap-tab[data-tab="tests"]');
  assert.equal(tab.textContent, "Tests (2)");
  const cards = root.querySelectorAll('[data-panel="tests"] .ap-ts-card');
  assert.equal(cards.length, 2);
  assert.match(cards[0].textContent, /T1/);
  assert.match(root.querySelector(".ap-tt-unmatched").textContent, /T9/);
});

test("a theory page without tests keeps its three columns and four tabs", () => {
  const data = { theories: [{ id: "theory-1", name: "Theory one", query: "Q", statements: [] }] };
  const { document, ctx } = page(
    `<div class="asta-panel asta-theories"></div>` +
    `<script type="application/json" class="asta-theories-data" id="asta-theories-data">${JSON.stringify(data)}</script>`);
  vm.runInNewContext(theoriesJs, ctx);
  assert.equal(document.querySelectorAll(".ap-tt thead th").length, 3);
  assert.equal(document.querySelectorAll(".ap-theory .ap-tab").length, 4);
});
