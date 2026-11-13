import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseHTML } from "linkedom";

// A code block in a wholly added or removed block is drawn on the shade like the text around
// it: the page's text colour, no background of its own, whatever the site's stylesheet gives it.
const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const script = `
import importlib.util, json
spec = importlib.util.spec_from_file_location("wc", "plugins/asta-tools/skills/workspace/assets/what-changed.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
same = "<p>Same page.</p>"
cases = {
  "stylesheet box": same + '<div class="codehilite"><pre><code>plain black code</code></pre></div>',
  "standalone pre": same + "<pre>plain black output</pre>",
  "standalone pre code": same + "<pre><code>plain black code</code></pre>",
  "inside a note": same + '<div class="note"><p>Run:</p><pre><code>black text</code></pre></div>',
  "highlighted": same + '<div class="sourceCode"><pre class="sourceCode python"><code class="sourceCode python"><span class="kw">def</span> f()</code></pre></div>',
}
removed = {k: m.diff_content(v, same)[0] for k, v in cases.items()}
added = {k: m.diff_content(same, v)[0] for k, v in cases.items()}
print(json.dumps({"css": m.DIFF_STYLE, "added": added, "removed": removed}))
`;
const run = spawnSync("python3", ["-I", "-c", script], { cwd: repoRoot, encoding: "utf8" });
assert.equal(run.status, 0, run.stderr);
const { css, added, removed } = JSON.parse(run.stdout);

// The rules of the stylesheet that set a code block's colour or background.
const rules = (property) => [...css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{([^{}]*)\}/g)]
  .filter(([, selector, body]) => /:is\(pre, pre code\)/.test(selector) &&
    new RegExp(`(?<![-\\w])${property}:`).test(body))
  .map(([, selector, body]) => ({ selector: selector.trim(), body }));
const colourRules = rules("color");
const backgroundRules = rules("background");
assert.equal(colourRules.length, 1);
assert.equal(backgroundRules.length, 1, JSON.stringify(backgroundRules));
assert.match(colourRules[0].body, /color:\s*inherit/);
assert.match(backgroundRules[0].body, /background:\s*none/);

const matches = (el, rule) => el.matches(rule.selector.replace(/^\.wc-scope /, ""));
const page = (body) => parseHTML(`<html><body><div class="wc-scope">${body}</div></body></html>`).document;

// The code boxes of each case: every pre and code in it that sits in, or is, a changed block.
function boxes(body) {
  const document = page(body);
  return [...document.querySelectorAll("pre, code")];
}

// Contrast of the page's text colours (GitHub's and Bootstrap's, light and dark) on each shade.
const luminance = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
const shade = (side, mode) => {
  const scope = mode === "dark" ? /\[data-wc-mode="dark"\] \.wc-scope\s*\{([^{}]*)\}/ : /\.wc-scope\s*\{([^{}]*)\}/;
  const root = css.match(scope)[1];
  return root.match(new RegExp(`--wc-${side}-blk:\\s*(#[0-9a-f]{6})`))[1];
};
const texts = { light: ["#1f2328", "#212529"], dark: ["#e6edf3", "#dee2e6"] };

for (const [side, set] of [["ins", added], ["del", removed]]) {
  for (const name of ["stylesheet box", "standalone pre", "standalone pre code", "inside a note"]) {
    test(`${name}, ${side === "ins" ? "added" : "removed"}: plain code takes the page's text colour on the shade`, () => {
      const found = boxes(set[name]);
      assert.ok(found.length >= 1);
      for (const el of found) {
        assert.ok(matches(el, colourRules[0]), `colour rule misses ${el.outerHTML}`);
      }
      // A box inside the changed block loses its own background; one that is the changed block keeps the shade.
      const inside = found.filter((el) => !el.classList.contains("wc-block-added") && !el.classList.contains("wc-block-removed"));
      for (const el of inside) {
        assert.ok(matches(el, backgroundRules[0]), `background rule misses ${el.outerHTML}`);
      }
      for (const el of found.filter((e) => !inside.includes(e))) {
        assert.ok(!matches(el, backgroundRules[0]), "the changed block itself keeps its shade");
      }
      for (const mode of ["light", "dark"]) {
        for (const text of texts[mode]) assert.ok(contrast(text, shade(side, mode)) >= 4.5, `${text} on ${mode} ${side}`);
      }
    });
  }
  test(`highlighted code keeps its own box and colours, ${side}`, () => {
    for (const el of boxes(set["highlighted"])) {
      assert.ok(!matches(el, colourRules[0]), `colour rule hits ${el.outerHTML}`);
      assert.ok(!matches(el, backgroundRules[0]), `background rule hits ${el.outerHTML}`);
    }
    for (const span of page(set["highlighted"]).querySelectorAll("span.kw")) {
      assert.ok(!matches(span, colourRules[0]));
    }
  });
}
