import assert from "node:assert/strict";
import fs from "node:fs";

import { parseHTML } from "linkedom";

const { document } = parseHTML(fs.readFileSync(process.argv[2], "utf8"));
const rules = [...document.querySelectorAll("style")].flatMap((style) =>
  [...style.sheet.cssRules].filter((rule) => rule.selectorText?.includes(".asta-diff-")),
);
for (const [selector, text, background, decoration] of [
  [".asta-diff-add", "Updated preview", "#d7f5dd", "none"],
  [".asta-diff-del", "Dev container", "#ffd7d5", "line-through"],
]) {
  const marks = [...document.querySelectorAll(selector)];
  assert.ok(marks.length, `LaTeXML produced no ${selector} marks`);
  assert.ok(marks.some((mark) => mark.textContent.includes(text)));
  for (const mark of marks) {
    const matched = rules.filter((rule) => mark.matches(rule.selectorText));
    assert.ok(matched.some((rule) => rule.style.background === background));
    assert.ok(matched.some((rule) => rule.style["text-decoration"] === decoration));
  }
}
const authorStrike = [...document.querySelectorAll(".ltx_ulem_sout")].find(
  (mark) => mark.textContent.includes("author strikethrough"),
);
assert.ok(authorStrike, "ordinary author strikethrough must survive conversion");
assert.equal(
  rules.some((rule) => authorStrike.matches(rule.selectorText)),
  false,
  "the diff palette must not restyle ordinary author strikethrough",
);
console.log("Real LaTeXML add/delete elements match the inline diff palette");
