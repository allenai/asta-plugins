import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseHTML } from "linkedom";

const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "what-changed-theme-"));
let generatedPage;
try {
  fs.mkdirSync(path.join(fixture, "old"));
  fs.mkdirSync(path.join(fixture, "new"));
  fs.writeFileSync(path.join(fixture, "new/index.html"), `<!doctype html><html><head>
    <link href="base.css" rel="stylesheet" class="quarto-color-scheme" data-mode="light">
    <link href="dark.css" rel="prefetch" class="quarto-color-scheme quarto-color-alternate" data-mode="dark">
    <link href="extra.css" rel="stylesheet" class="quarto-color-scheme-extra" data-mode="light">
    <link href="extra-both.css" rel="stylesheet" class="quarto-color-scheme quarto-color-scheme-extra" data-mode="light">
    <link href="syntax.css" rel="stylesheet" class="quarto-color-scheme">
    <link href="syntax-dark.css" rel="stylesheet" class="quarto-color-scheme quarto-color-alternate">
    <link href="custom.css" rel="stylesheet">
    <script>const authorPrefersDark = true; const darkModeDefault = authorPrefersDark;</script>
    </head><body><main><p>New content</p></main></body></html>`);
  const generated = spawnSync("python3", [
    "plugins/asta-tools/skills/workspace/assets/what-changed.py",
    "--old", path.join(fixture, "old"), "--new", path.join(fixture, "new"),
    "--out", path.join(fixture, "diff.html"),
  ], { cwd: repoRoot, encoding: "utf8" });
  assert.equal(generated.status, 0, generated.stderr);
  generatedPage = fs.readFileSync(path.join(fixture, "diff.html"), "utf8");
} finally {
  fs.rmSync(fixture, { recursive: true, force: true });
}
const modeScript = generatedPage.match(/<script>([\s\S]*?localStorage[\s\S]*?)<\/script>/)[1];

function assertTheme(document, mode) {
  assert.equal(document.documentElement.dataset.wcMode, mode);
  assert.ok(document.body.classList.contains(`quarto-${mode}`));
  const rel = (href) => document.querySelector(`link[href="${href}"]`).getAttribute("rel");
  assert.equal(rel("base.css"), "stylesheet", "Base styles survive in either mode");
  assert.equal(rel("syntax.css"), "stylesheet");
  assert.equal(rel("dark.css"), mode === "dark" ? "stylesheet" : "disabled-stylesheet");
  assert.equal(rel("syntax-dark.css"), mode === "dark" ? "stylesheet" : "disabled-stylesheet");
  assert.equal(rel("extra.css"), "disabled-stylesheet");
  assert.equal(rel("extra-both.css"), "disabled-stylesheet");
  assert.equal(rel("custom.css"), "stylesheet");
}

test("server output preserves base styles and disables extras before JavaScript", () => {
  assertTheme(parseHTML(generatedPage).document, "dark");
});

for (const scenario of [
  { name: "dark default with a light OS", stored: null, systemDark: false, mode: "dark" },
  { name: "saved light with a dark OS", stored: "default", systemDark: true, mode: "light" },
  { name: "saved dark with a light OS", stored: "alternate", systemDark: false, mode: "dark" },
  { name: "system preference when opted in", stored: null, followSystem: true, systemDark: false, mode: "light" },
  { name: "system dark when opted in", stored: null, followSystem: true, systemDark: true, mode: "dark" },
  { name: "saved light overrides system opt-in", stored: "default", followSystem: true, systemDark: true, mode: "light" },
  { name: "unavailable storage preserves dark default", storageThrows: true, mode: "dark" },
]) {
  test(scenario.name, () => {
    const { document } = parseHTML(generatedPage);
    if (scenario.followSystem) document.documentElement.dataset.wcFollowSystem = "true";
    const window = {
      localStorage: { getItem(key) {
        assert.equal(key, "quarto-color-scheme");
        if (scenario.storageThrows) throw new Error("Storage unavailable");
        return scenario.stored;
      } },
      matchMedia: () => ({ matches: scenario.systemDark }),
    };
    new Function("document", "window", modeScript)(document, window);
    assertTheme(document, scenario.mode);
    new Function("document", "window", modeScript)(document, window);
    assertTheme(document, scenario.mode);
  });
}
