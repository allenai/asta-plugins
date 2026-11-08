import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseHTML } from "linkedom";

const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const generated = spawnSync("python3", ["-c", `
import importlib.util, json
spec = importlib.util.spec_from_file_location("review", "plugins/asta-tools/skills/workspace/assets/deck-review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
print(json.dumps({"script": review.SCRIPT, "style": review.STYLE}))
`], { cwd: repoRoot, encoding: "utf8" });
assert.equal(generated.status, 0, generated.stderr);
const { script, style } = JSON.parse(generated.stdout);

function report(words) {
  const data = {
    items: [{ n: 1, kind: "changed", title: "Title", clean: "c.png", marked: "m.png",
      before: "b.png", link: "slides.html#/title" }],
    removed: [{ n: 2, title: "Removed", img: "r.png" }],
    total: 1,
    text: { "m.png": words, "c.png": [["Clean", .1, .2, .1, .1]],
      "b.png": [["Before", .1, .2, .1, .1]], "r.png": [["Removed", .1, .2, .1, .1]] },
  };
  const { document } = parseHTML(`<!doctype html><html><head>${style}</head><body>
    <div class="deck-review"><span class="dr-count"></span>
      <div class="dr-seg"><button data-v="marked">Changes marked</button>
        <button data-v="clean">Clean</button><button data-v="before">Before / after</button></div>
      <div class="dr-list"></div><script class="dr-data" type="application/json">${JSON.stringify(data)}</script>
    </div></body></html>`);
  const createElement = document.createElement.bind(document);
  document.createElement = (tag) => {
    const element = createElement(tag);
    // These tests exercise word order and accessibility, not font measurement.
    if (tag === "canvas") element.getContext = () => ({ measureText: t => ({ width: t.length * 50 }) });
    return element;
  };
  Function("document", "getComputedStyle", script.replace(/^<script>|<\/script>$/g, ""))(
    document, () => ({ fontFamily: "sans-serif" }),
  );
  return document;
}

test("superscripts and subscripts stay on their line when copied", () => {
  const document = report([
    ["Energy", .1, .2, .1, .1],
    ["2", .21, .15, .02, .06], // Raised enough to fool the old half-height test.
    ["and", .24, .2, .07, .1],
    ["x", .32, .2, .02, .1],
    ["i", .35, .26, .02, .06],
    ["vary", .38, .2, .08, .1],
    ["Next", .1, .4, .08, .1],
    ["line", .2, .4, .08, .1],
  ]);
  assert.equal(document.querySelector(".dr-shot .dr-text").textContent,
    "Energy 2 and x i vary\nNext line\n");
});

test("selectable words are exposed once through the image description in every mode", () => {
  const document = report([["Marked", .1, .2, .1, .1]]);
  const main = document.querySelector(".dr-shot[data-clean]");
  for (const mode of ["marked", "clean", "before", "marked"]) {
    document.querySelector(`.dr-seg button[data-v="${mode}"]`).click();
    const expected = mode === "clean" ? "Clean" : "Marked";
    assert.equal(main.querySelector(".dr-text").textContent, expected + "\n");
    assert.equal(main.querySelector("img").alt, `Slide 1: Title (${mode === "clean" ? "clean" : "marked"})\n${expected}`);
    for (const layer of document.querySelectorAll(".dr-text")) {
      assert.equal(layer.getAttribute("aria-hidden"), "true");
      assert.ok(layer.textContent.trim(), "words remain available for selection");
      const image = layer.parentElement.querySelector("img");
      assert.ok(image.alt.endsWith("\n" + layer.textContent.trim()), image.alt);
    }
  }
});

test("older comparisons without recorded text keep the slide label", () => {
  const document = report([]);
  assert.equal(document.querySelector(".dr-shot img").alt, "Slide 1: Title (marked)");
});
