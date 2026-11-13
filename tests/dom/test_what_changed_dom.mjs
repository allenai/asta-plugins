import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseHTML } from "linkedom";

const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), "what-changed-dom-"));
const oldRoot = path.join(fixtureRoot, "old");
const newRoot = path.join(fixtureRoot, "new");
const outputPath = path.join(fixtureRoot, "what-changed.html");
fs.mkdirSync(oldRoot);
fs.mkdirSync(newRoot);
fs.writeFileSync(
  path.join(newRoot, "index.html"),
  "<html><head></head><body><main><p>new page</p></main></body></html>",
);
const generated = spawnSync(
  "python3",
  [
    "plugins/asta-tools/skills/workspace/assets/what-changed.py",
    "--old",
    oldRoot,
    "--new",
    newRoot,
    "--out",
    outputPath,
  ],
  { cwd: repoRoot, encoding: "utf8" },
);
assert.equal(generated.status, 0, generated.stderr);
const generatedPage = fs.readFileSync(outputPath, "utf8");
fs.rmSync(fixtureRoot, { recursive: true, force: true });
const foldScript = generatedPage.match(
  /<script>\s*(\(function \(\) \{[\s\S]*?)<\/script>/,
);
assert.ok(foldScript, "generated page must contain the folding script");

const longText = "unchanged supporting content ".repeat(30);

test("folder only inserts disclosures into valid flow containers", () => {
  const { document, window } = parseHTML(`<!doctype html><html><body>
    <section class="page-diff changed"><div class="diff-body">
      <div id="block-parent">
        <section id="fold-me">${longText}</section>
        <p><ins>changed block</ins></p>
      </div>
      <p id="paragraph-parent">
        <span>${longText}</span><ins><span id="inserted">new evidence</span></ins>
      </p>
      <h2 id="heading-parent">
        <span>${longText}</span><ins>changed heading</ins>
      </h2>
      <details open><summary id="summary-parent">
        <span>${longText}</span><ins>changed summary</ins>
      </summary></details>
      <table><tbody id="table-parent">
        <tr><td>${longText}</td></tr><tr><td><ins>changed cell</ins></td></tr>
      </tbody></table>
      <ul id="list-parent">
        <li>${longText}</li><li><ins>changed item</ins></li>
      </ul>
      <div id="popover-parent">
        <span id="tooltip" style="position: absolute">
          <span>${longText}</span><span>${longText}</span>
        </span>
        <p><ins>changed claim</ins></p>
      </div>
    </div></section>
  </body></html>`);

  window.getComputedStyle = (element) => ({
    display: element.style?.display || "block",
    visibility: element.style?.visibility || "visible",
    position: element.style?.position || "static",
  });

  Function("document", foldScript[1])(document);

  // Prove the folder actually ran: a long unchanged block beside a change is
  // hidden behind a strip when its parent is an allowed flow-content container.
  const strip = document.querySelector("#block-parent > .wc-strip");
  assert.ok(strip);
  assert.match(strip.textContent, /⋯ 1 unchanged section$/);
  assert.ok(document.getElementById("fold-me").hasAttribute("hidden"));
  assert.equal(document.getElementById("fold-me").textContent, longText);

  // Phrasing-only and structured parents never receive a block disclosure.
  // This catches a removed, inverted, or unused eligibility guard.
  for (const id of [
    "paragraph-parent",
    "heading-parent",
    "summary-parent",
    "inserted",
    "tooltip",
  ]) {
    const parent = document.getElementById(id);
    assert.ok(parent, `missing test fixture #${id}`);
    assert.equal(
      [...parent.children].some((child) => child.matches(".wc-strip")),
      false,
      `folder inserted an invalid strip directly inside #${id}`,
    );
  }

  // A list and a table body take a strip of their own kind (an li, a row with
  // one cell across the table), never a div.
  const listStrip = document.querySelector("#list-parent > .wc-strip");
  assert.equal(listStrip?.tagName, "LI");
  assert.match(listStrip.textContent, /⋯ 1 unchanged list item$/);
  const rowStrip = document.querySelector("#table-parent > .wc-strip");
  assert.equal(rowStrip?.tagName, "TR");
  assert.equal(rowStrip.children.length, 1);
  assert.equal(rowStrip.children[0].tagName, "TD");

  assert.equal(document.querySelector("#inserted")?.textContent, "new evidence");
  assert.equal(document.querySelectorAll("#tooltip .wc-strip").length, 0);
});

const stubStyles = (window) => {
  window.getComputedStyle = () => ({
    display: "block",
    visibility: "visible",
    position: "static",
  });
};

test("source lines fold behind one strip whose arrows open 20 at a time", () => {
  const lines = Array.from({ length: 60 }, (_, i) => `<div class="wc-ln">line ${i}</div>`);
  lines[0] = '<div class="wc-ln"><ins>first</ins></div>';
  lines[59] = '<div class="wc-ln"><del>last</del></div>';
  const { document, window } = parseHTML(
    `<!doctype html><html><body><div class="wc-src">${lines.join("")}</div></body></html>`,
  );
  stubStyles(window);
  Function("document", foldScript[1])(document);

  const src = document.querySelector(".wc-src");
  const strip = src.querySelector(".wc-strip");
  assert.ok(strip, "the gap between the two changes is folded");
  const hiddenCount = () => src.querySelectorAll(".wc-ln[hidden]").length;
  // 3 lines of context beside each change stay; the other 60 - 2 - 6 are hidden.
  assert.equal(hiddenCount(), 52);
  assert.match(strip.textContent, /52 unchanged lines/);
  const [down, up, more] = strip.querySelectorAll("button");

  down.click(); // 20 more below the change above
  assert.equal(hiddenCount(), 32);
  assert.ok(strip.previousElementSibling.textContent.startsWith("line"));
  assert.match(strip.textContent, /32 unchanged lines/);
  up.click(); // 20 more above the change below
  assert.equal(hiddenCount(), 12);
  more.click(); // all
  assert.equal(hiddenCount(), 0);
  assert.equal(src.querySelector(".wc-strip"), null, "an emptied strip goes away");
});

test("a gap at either end offers only the arrow that leads to a change", () => {
  const lines = Array.from({ length: 30 }, (_, i) => `<div class="wc-ln">line ${i}</div>`);
  lines[15] = '<div class="wc-ln"><ins>new</ins></div>';
  const { document, window } = parseHTML(
    `<!doctype html><html><body><div class="wc-src">${lines.join("")}</div></body></html>`,
  );
  stubStyles(window);
  Function("document", foldScript[1])(document);

  const [first, last] = document.querySelectorAll(".wc-strip");
  assert.match(first.textContent, /12 unchanged lines/);
  const hidden = (strip) => [...strip.querySelectorAll("button")].map((b) => b.hasAttribute("hidden"));
  assert.deepEqual(hidden(first), [true, false, false], "top: only up, toward the change");
  assert.deepEqual(hidden(last), [false, true, false], "bottom: only down");
});

// The engine's own output for an edit that has no <ins>/<del>: a link's target,
// formatting put on kept words, evidence added to kept prose. A long paragraph
// beside it must not fold the edit away as unchanged.
const diffContent = (oldHtml, newHtml) => {
  const run = spawnSync(
    "python3",
    [
      "-c",
      [
        "import importlib.util, json, sys",
        "spec = importlib.util.spec_from_file_location('wc', sys.argv[1])",
        "wc = importlib.util.module_from_spec(spec)",
        "spec.loader.exec_module(wc)",
        "print(json.dumps(wc.diff_content(sys.argv[2], sys.argv[3])))",
      ].join("\n"),
      path.join(repoRoot, "plugins/asta-tools/skills/workspace/assets/what-changed.py"),
      oldHtml,
      newHtml,
    ],
    { encoding: "utf8" },
  );
  assert.equal(run.status, 0, run.stderr);
  return JSON.parse(run.stdout);
};

const prose = "unchanged supporting prose ".repeat(20);
const pop = (quote) =>
  `<span class="ev-pop" role="note"><span class="ev-card">${quote}</span></span>`;
const markerOnlyEdits = {
  "a link target": [
    `<p>${prose}<a href="a.html">the docs</a></p>`,
    `<p>${prose}<a href="b.html">the docs</a></p>`,
  ],
  "formatting on kept words": [
    `<p>${prose}the docs</p>`,
    `<p>${prose}<em>the docs</em></p>`,
  ],
  "evidence added to kept prose": [
    `<p>${prose}<span class="ev" role="note">claim</span></p>`,
    `<p>${prose}<span class="ev" role="note">claim${pop("quote")}</span></p>`,
  ],
};

for (const [name, [before, after]] of Object.entries(markerOnlyEdits)) {
  test(`an edit with only ${name} is not folded away`, () => {
    const [body, changed] = diffContent(before, after);
    assert.equal(changed, true);
    assert.doesNotMatch(body, /<(ins|del)[\s>]/, "the case has no word marks");
    const { document, window } = parseHTML(
      `<!doctype html><html><body><section class="page-diff changed"><div class="diff-body">` +
        `<p>${prose}</p>${body}<p>${prose}</p></div></section></body></html>`,
    );
    stubStyles(window);
    Function("document", foldScript[1])(document);

    // The edit is drawn once, between the two unchanged paragraphs.
    const blocks = [...document.querySelectorAll(".diff-body > p")];
    assert.equal(blocks.length, 3, "one copy of the edit");
    assert.equal(blocks[1].hasAttribute("hidden"), false, "the edit is hidden");
  });
}

// A page outside the workspace follows the header of diff-engine.py: the
// fragment goes in `<div class="wc-scope wc-standalone" data-wc-fold>`, and
// FOLD_JS (from the engine, not from a generated page) folds it with no call.
const outsidePage = (oldHtml, newHtml, oldText, newText) => {
  const run = spawnSync(
    "python3",
    [
      "-c",
      [
        "import importlib.util, json, sys",
        "spec = importlib.util.spec_from_file_location('engine', sys.argv[1])",
        "engine = importlib.util.module_from_spec(spec)",
        "spec.loader.exec_module(engine)",
        "print(json.dumps({'js': engine.FOLD_JS,",
        "  'page': engine.diff_content(sys.argv[2], sys.argv[3])[0],",
        "  'source': engine.source_diff(sys.argv[4], sys.argv[5])}))",
      ].join("\n"),
      path.join(repoRoot, "plugins/asta-tools/skills/workspace/assets/diff-engine.py"),
      oldHtml,
      newHtml,
      oldText,
      newText,
    ],
    { encoding: "utf8" },
  );
  assert.equal(run.status, 0, run.stderr);
  return JSON.parse(run.stdout);
};

test("a long unchanged stretch in the outside-page wrapper folds behind one strip", () => {
  const unchanged = Array.from({ length: 6 }, (_, i) => `<p>${prose} ${i}</p>`).join("");
  const { js, page } = outsidePage(
    `<p>old claim</p>${unchanged}<p>tail</p>`,
    `<p>new claim</p>${unchanged}<p>tail</p>`,
    "",
    "",
  );
  const { document, window } = parseHTML(
    `<!doctype html><html><body><div class="wc-scope wc-standalone" data-wc-fold>${page}</div></body></html>`,
  );
  stubStyles(window);
  Function("document", js)(document);

  const strips = document.querySelectorAll(".wc-standalone > .wc-strip");
  assert.equal(strips.length, 1);
  assert.match(strips[0].textContent, /⋯ 7 unchanged paragraphs$/);
});

test("a source fragment in the outside-page wrapper folds once", () => {
  const lines = Array.from({ length: 40 }, (_, i) => `line ${i}`);
  const { js, source } = outsidePage("", "", lines.join("\n"), ["edited", ...lines.slice(1)].join("\n"));
  const { document, window } = parseHTML(
    `<!doctype html><html><body><div class="wc-scope wc-standalone" data-wc-fold>${source}</div></body></html>`,
  );
  stubStyles(window);
  Function("document", js)(document);

  assert.equal(document.querySelectorAll(".wc-strip").length, 1, "one strip, not one per initializer");
});

const fold = (body) => {
  const { document, window } = parseHTML(
    `<!doctype html><html><body><section class="page-diff changed"><div class="diff-body">${body}</div></section></body></html>`,
  );
  stubStyles(window);
  Function("document", foldScript[1])(document);
  return document;
};
const item = (i) => `<li>item ${i} ${longText}</li>`;

test("a one-line edit in a bullet list folds the list's unchanged items", () => {
  const items = Array.from({ length: 10 }, (_, i) =>
    i === 4 ? "<li>item 4 <ins>edited</ins></li>" : item(i),
  );
  const document = fold(`<ul id="l">${items.join("")}</ul>`);
  const list = document.getElementById("l");
  const strips = [...list.children].filter((c) => c.matches(".wc-strip"));
  assert.equal(strips.length, 2);
  assert.ok(strips.every((s) => s.tagName === "LI"));
  // (neighbours this long are not kept as context)
  assert.match(strips[0].textContent, /⋯ 4 unchanged list items$/);
  assert.match(strips[1].textContent, /⋯ 5 unchanged list items$/);
  const shown = [...list.children].filter((c) => !c.matches(".wc-strip") && !c.hasAttribute("hidden"));
  assert.equal(shown.length, 1, "only the edited item");

  // the text opens them all, and the strip goes
  strips[0].querySelector(".wc-more").click();
  assert.equal(list.querySelectorAll("li[hidden]").length, 5);
  assert.equal([...list.children].filter((c) => c.matches(".wc-strip")).length, 1);
});

test("a folded ordered list keeps its numbers", () => {
  const items = Array.from({ length: 10 }, (_, i) =>
    i === 7 ? "<li>item 7 <ins>edited</ins></li>" : item(i),
  );
  const document = fold(`<ol id="l" start="3">${items.join("")}</ol>`);
  const list = document.getElementById("l");
  const visible = [...list.children].filter((c) => c.tagName === "LI" && !c.matches(".wc-strip") && !c.hasAttribute("hidden"));
  // only item 7 stays, number 10 of a list that starts at 3: it says so
  assert.equal(visible.length, 1);
  assert.equal(visible[0].getAttribute("value"), "10");
});

test("a table body's unchanged rows fold behind a row with one cell across the table", () => {
  const row = (i) => `<tr><td>row ${i} ${longText}</td><td>x</td><td>y</td></tr>`;
  const rows = Array.from({ length: 7 }, (_, i) =>
    i === 3 ? "<tr><td>row 3 <ins>edited</ins></td><td>x</td><td>y</td></tr>" : row(i),
  );
  const document = fold(`<table><tbody id="b">${rows.join("")}</tbody></table>`);
  const body = document.getElementById("b");
  const strips = [...body.children].filter((c) => c.matches(".wc-strip"));
  assert.equal(strips.length, 2);
  for (const s of strips) {
    assert.equal(s.tagName, "TR");
    assert.equal(s.children.length, 1);
    assert.equal(s.children[0].getAttribute("colspan"), "3");
  }
  assert.match(strips[0].textContent, /⋯ 3 unchanged table rows$/);
  assert.equal(body.querySelectorAll("tr[hidden]").length, 6);
});

test("a fold strip names what it hides in a reader's terms, and again as the arrows open it", () => {
  const long = (tag) => `<${tag}>${longText}</${tag}>`;
  const edited = "<p><ins>edited</ins></p>";
  const document = fold(
    `<div id="two">${edited}${long("p")}${long("p")}<ul><li>${longText}</li></ul>${edited}</div>` +
      `<div id="three">${edited}${long("p")}<ul><li>${longText}</li></ul><table><tbody><tr><td>${longText}</td></tr></tbody></table>${edited}</div>` +
      `<div id="callout">${edited}<div class="callout">${longText}</div>${edited}</div>` +
      `<ul id="many">${edited.replace(/p>/g, "li>")}${Array.from({ length: 25 }, (_, i) => item(i)).join("")}${edited.replace(/p>/g, "li>")}</ul>`,
  );
  const text = (id) => document.querySelector(`#${id} > .wc-strip`).textContent;
  // two kinds are both named
  assert.match(text("two"), /⋯ 2 unchanged paragraphs and 1 list$/);
  // past two, they are parts
  assert.match(text("three"), /⋯ 3 unchanged parts$/);
  // a class a reader knows names it
  assert.match(text("callout"), /⋯ 1 unchanged callout$/);
  // the arrow opens 20 and the strip says what is left
  assert.match(text("many"), /⋯ 25 unchanged list items$/);
  document.querySelector("#many > .wc-strip button").click();
  assert.match(text("many"), /⋯ 5 unchanged list items$/);
});

test("a wholly added block with a hanging first line grows left by the overhang, so that its shade covers the first line", () => {
  const { document, window } = parseHTML(`<!doctype html><html><body>
    <section class="page-diff changed"><div class="diff-body">
      <div id="ref" class="wc-block-added"><ins>Smith, J. (2020). A hanging reference.</ins></div>
      <div id="plain" class="wc-block-removed"><del>An ordinary block.</del></div>
    </div></section></body></html>`);
  window.getComputedStyle = (element) => ({
    display: "block",
    visibility: "visible",
    position: "static",
    textIndent: element.id === "ref" ? "-32px" : "0px",
    marginLeft: "8px",
    paddingLeft: "0px",
  });
  Function("document", foldScript[1])(document);
  const ref = document.getElementById("ref");
  assert.equal(ref.style.marginLeft, "-24px", "the box starts 32px further left");
  assert.equal(ref.style.paddingLeft, "32px", "its text stays where it was");
  const plain = document.getElementById("plain");
  assert.equal(plain.style.marginLeft, "");
  assert.equal(plain.style.paddingLeft, "");
});
