import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseHTML } from "linkedom";

const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), "what-changed-paper-dom-"));
const oldRoot = path.join(fixtureRoot, "old");
const newRoot = path.join(fixtureRoot, "new");
const outputPath = path.join(fixtureRoot, "what-changed.html");
fs.mkdirSync(oldRoot);
fs.mkdirSync(path.join(newRoot, "paper-previews/paper"), { recursive: true });
fs.writeFileSync(
  path.join(newRoot, "paper-previews/paper/preview.json"),
  JSON.stringify({ changed: true, diff: true }),
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
const paperScript = [...generatedPage.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(match => match[1])
  .find(source => source.includes(".paper-view"));
assert.ok(paperScript, "generated page must contain the paper viewer's script");

function report() {
  const { document, window } = parseHTML(generatedPage);
  Function("document", paperScript)(document);
  const press = key => {
    const event = new window.Event("keydown");
    event.key = key;
    document.dispatchEvent(event);
  };
  return { document, press };
}

test("the paper opens on its changes marked, with a switch to the clean paper", () => {
  const { document } = report();
  const data = () => document.querySelector(".paper-view object").getAttribute("data");
  assert.equal(data(), "paper-previews/paper/what-changed.pdf#navpanes=0&view=FitH");
  document.querySelector('.paper-modes [data-pdf$="main.pdf"]').click();
  assert.equal(data(), "paper-previews/paper/main.pdf#navpanes=0&view=FitH");
  assert.deepEqual(
    [...document.querySelectorAll(".paper-modes button")].map(b => b.getAttribute("aria-pressed")),
    ["false", "true"],
  );
  // The fallback link stays inside the new frame and opens the PDF chosen.
  assert.equal(document.querySelector(".paper-view object a").getAttribute("href"),
    "paper-previews/paper/main.pdf");
});

test("the expand button gives the paper the whole window, and Esc gives the report back", () => {
  const { document, press } = report();
  const view = document.querySelector(".paper-view");
  document.querySelector(".paper-expand").click();
  assert.equal(view.classList.contains("paper-full"), true);
  assert.equal(document.body.style.overflow, "hidden");
  press("Escape");
  assert.equal(view.classList.contains("paper-full"), false);
  assert.equal(document.body.style.overflow, "");
});
