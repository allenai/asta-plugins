import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseHTML } from "linkedom";

// The live deck view as deck-review.py builds it: slide 3 of 4 changed.
const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const generated = spawnSync("python3", ["-I", "-c", `
import importlib.util, json, os, sys, tempfile
assets = os.path.join(sys.argv[1], "plugins/asta-tools/skills/workspace/assets")
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(assets, file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
review = load("review", "deck-review.py")
wc = load("wc", "what-changed.py")
def deck(*bodies):
    sections = "".join(f'<section id="s{i}"><h2>S{i}</h2><p>{b}</p></section>' for i, b in enumerate(bodies, 1))
    return f'<html><head></head><body><div class="reveal"><div class="slides">{sections}</div></div></body></html>'
old_doc, new_doc = deck("a", "b", "old words", "d"), deck("a", "b", "new words", "d")
root = tempfile.mkdtemp()
for side, doc in (("old", old_doc), ("new", new_doc)):
    os.makedirs(os.path.join(root, side, "d"))
    with open(os.path.join(root, side, "d/deck.html"), "w") as f:
        f.write(doc)
old, new = wc.reveal_slides(old_doc), wc.reveal_slides(new_doc)
files = review.StaticFiles(os.path.join(root, "old"), os.path.join(root, "new"))
body, *_ = review.live_review("d/deck.html", old_doc, new_doc, old, new,
    {i: i for i in range(4)}, files, "b.html", "a.html")
print(json.dumps({"body": body, "script": review.LIVE_SCRIPT}))
`, repoRoot], { encoding: "utf8" });
assert.equal(generated.status, 0, generated.stderr);
const { body, script } = JSON.parse(generated.stdout);

function page(withObserver = false) {
  const { document, window } = parseHTML(`<!doctype html><html><body>${body}</body></html>`);
  // linkedom has no layout: a figure shows when its view is the page's (LIVE_STYLE's rule).
  Object.defineProperty(window.HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get() {
      const root = this.closest(".deck-live");
      const views = (this.getAttribute("data-view") || "").split(" ");
      return root && views.includes(root.getAttribute("data-view")) ? document.body : null;
    },
  });
  // linkedom frames have no window: stand in for a sandboxed frame, which only takes
  // messages. Reaching into it (Reveal, document) throws, as it does cross-origin.
  Object.defineProperty(window.HTMLElement.prototype, "contentWindow", {
    configurable: true,
    get() {
      const fail = () => { throw new Error("a sandboxed frame is opaque"); };
      return new Proxy({}, {
        get: (_, key) => key === "postMessage"
          ? (message, origin) => {
              this.messages = (this.messages || []).concat([message]);
              this.layouts = (this.layouts || 0) + (JSON.parse(message).method === "layout" ? 1 : 0);
              assert.equal(origin, "*", "an opaque origin is only reachable with '*'");
            }
          : fail(),
      });
    },
  });
  let observer;
  if (withObserver) {
    window.IntersectionObserver = class {
      constructor(callback) { this.callback = callback; this.targets = new Set(); observer = this; }
      observe(frame) { this.targets.add(frame); }
      unobserve(frame) { this.targets.delete(frame); }
    };
    window.HTMLElement.prototype.getBoundingClientRect = () => ({top: 0});
  }
  Function("document", "window", "IntersectionObserver", "setTimeout", script.replace(/^<script>|<\/script>$/g, ""))(document, window, window.IntersectionObserver, () => 0);
  return { document, window, observer };
}

const loaded = (scope) =>
  [...scope.querySelectorAll("iframe[src]")].map(f => f.closest("figure").getAttribute("data-view"));

test("each view loads only its own frames, opened at the changed slide", () => {
  const { document } = page();
  assert.match(document.querySelector(".dr-count").textContent, /^1 changed or new; 0 removed; 4 slides/);
  assert.deepEqual(loaded(document), ["marked"]);
  assert.match(document.querySelector("iframe[src]").getAttribute("src"), /^a\.frame-marked-3\.html\?.*#\/s3$/);
  const steps = [["clean", ["marked", "clean"]], ["before", ["marked", "clean", "before", "before"]]];
  for (const [view, expected] of steps) {
    document.querySelector(`.dr-seg button[data-v="${view}"]`).click();
    assert.equal(document.querySelector(".deck-live").getAttribute("data-view"), view);
    assert.deepEqual(
      [...document.querySelectorAll(".dr-seg button")].map(b => b.getAttribute("aria-pressed")),
      ["marked", "clean", "before"].map(v => String(v === view)),
    );
    assert.deepEqual(loaded(document), expected);
  }
});

test("showing a view lays out its loaded frames, and only those", () => {
  const { document } = page();
  const frame = view => document.querySelector(`figure[data-view="${view}"] iframe`);
  const click = view => document.querySelector(`.dr-seg button[data-v="${view}"]`).click();
  const marked = frame("marked");
  click("clean");
  assert.equal(marked.layouts, undefined, "a hidden frame is left alone");
  assert.equal(frame("clean").layouts, 1, "the shown frame is laid out");
  click("marked");
  assert.equal(marked.layouts, 1, "a frame shown again is laid out at its size");
  assert.equal(frame("clean").layouts, 1);
  assert.deepEqual(marked.messages, ['{"method":"layout"}'], "Reveal's own message, nothing else");
});

test("folded unchanged slides load no deck until expanded", () => {
  const { document, window } = page();
  const folds = [...document.querySelectorAll("details.wc-expander")];
  assert.deepEqual(folds.map(d => d.querySelector("summary").textContent.trim()),
    ["↕ Expand 2 unchanged slides (1–2)", "↕ Expand 1 unchanged slide (4)"]);
  for (const details of folds) assert.equal(details.querySelectorAll("iframe").length, 0);
  const [first, second] = folds;
  if (!("open" in first)) Object.defineProperty(first, "open", { get() { return this.hasAttribute("open"); } });
  first.setAttribute("open", "");
  first.dispatchEvent(new window.Event("toggle"));
  assert.equal(first.querySelectorAll("template").length, 0);
  const ids = new Set([...first.querySelectorAll("iframe")].map(f => f.getAttribute("data-dr-slide-id")));
  assert.deepEqual([...ids], ["s1", "s2"]);
  assert.deepEqual(loaded(first), ["marked", "marked"], "only the shown view's frames load");
  assert.equal(second.querySelectorAll("iframe").length, 0);
});


test("viewport loader starts at most four frames and advances when one loads", () => {
  const { document, window, observer } = page(true);
  for (const fold of document.querySelectorAll("details.wc-expander")) {
    Object.defineProperty(fold, "open", { get() { return this.hasAttribute("open"); } });
    fold.setAttribute("open", "");
    fold.dispatchEvent(new window.Event("toggle"));
  }
  document.querySelector('.dr-seg button[data-v="before"]').click();
  assert.equal(loaded(document).length, 0, "observation alone does not load decks");
  const visible = [...observer.targets].filter(f => f.closest("figure").offsetParent !== null);
  assert.equal(visible.length, 8);
  observer.callback(visible.map(target => ({target, isIntersecting: true})));
  assert.equal(loaded(document).length, 4, "only four loads in flight");
  document.querySelector("iframe[src]").dispatchEvent(new window.Event("load"));
  assert.equal(loaded(document).length, 5, "the next frame starts after a load");
});
