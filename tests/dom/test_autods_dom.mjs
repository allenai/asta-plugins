import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

import { parseHTML } from "linkedom";

const code = fs.readFileSync(
  new URL("../../plugins/asta-tools/skills/workspace/assets/_extensions/asta-templates/autods.js", import.meta.url),
  "utf8",
);

// A local run as asta-templates.lua embeds it: its mcts_node records (node_1_0 loads the data).
const node = (id, idx, parent) => ({ id, creation_idx: idx, parent_id: parent, success: true, hypothesis: `About ${id}.` });
const RUN = { kind: "nodes", source: "run", nodes: [node("node_2_1", 2, "node_1_0"), node("node_3_1", 3, "node_2_1"), node("node_3_12", 4, "node_2_1")] };

function runPage(hash) {
  const { document } = parseHTML(
    `<!doctype html><html><body><div class="asta-panel asta-autods"></div>` +
    `<script type="application/json" id="asta-autods-data">${JSON.stringify({ runs: [RUN] })}</script></body></html>`);
  const listeners = {};
  const location = { hash };
  const window = { addEventListener: (type, fn) => (listeners[type] ??= []).push(fn), scrollY: 0, scrollTo() {} };
  class Observer { observe() {} disconnect() {} }
  document.defaultView.HTMLElement.prototype.scrollIntoView = function () {};
  vm.runInNewContext(code, {
    window, document, location, MutationObserver: Observer, getComputedStyle: () => ({ getPropertyValue: () => "" }),
    history: { pushState: (_, __, u) => { location.hash = u; }, replaceState: (_, __, u) => { location.hash = u; } },
  });
  const go = h => { location.hash = h; (listeners.hashchange ?? []).forEach(fn => fn()); };
  const selected = () => [...document.querySelectorAll(".ap-ad-exps tbody tr.ap-selected")].map(tr => tr.getAttribute("data-key"));
  return { document, go, selected };
}

test("a node id selects its experiment, as #experiment-N does", () => {
  const p = runPage("#node-3-1");
  assert.deepEqual(p.selected(), ["node_3_1"]);
  p.go("#node_3_12");
  assert.deepEqual(p.selected(), ["node_3_12"]);
  p.go("#experiment-1");
  assert.deepEqual(p.selected(), ["node_2_1"], "creation order: node_2_1 is experiment 1");
  p.go("#node-3-1");
  assert.deepEqual(p.selected(), ["node_3_1"]);
  p.go("#node-3-12x");
  assert.deepEqual(p.selected(), ["node_3_1"], "an id that is no node changes nothing");
});
