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
  // collapsed when its parent is an allowed flow-content container.
  const validFold = document.querySelector("#block-parent > details.wc-fold");
  assert.ok(validFold);
  assert.equal(validFold.querySelector("#fold-me")?.textContent, longText);

  // Phrasing-only and structured parents never receive a block disclosure.
  // This catches a removed, inverted, or unused eligibility guard.
  for (const id of [
    "paragraph-parent",
    "heading-parent",
    "summary-parent",
    "table-parent",
    "list-parent",
    "inserted",
    "tooltip",
  ]) {
    const parent = document.getElementById(id);
    assert.ok(parent, `missing test fixture #${id}`);
    assert.equal(
      [...parent.children].some((child) => child.matches("details.wc-fold")),
      false,
      `folder inserted an invalid disclosure directly inside #${id}`,
    );
  }

  assert.equal(document.querySelector("#inserted")?.textContent, "new evidence");
  assert.equal(document.querySelectorAll("#tooltip details.wc-fold").length, 0);
});
