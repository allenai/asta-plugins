import assert from "node:assert/strict";
import fs from "node:fs";

import { parseHTML } from "linkedom";

const { document } = parseHTML(fs.readFileSync(process.argv[2], "utf8"));
const rules = [...document.querySelectorAll("style")].flatMap((style) =>
  [...(style.sheet?.cssRules ?? [])].filter((rule) => rule.selectorText?.includes(".asta-diff-")),
);
for (const [selector, text, background, decoration] of [
  [".asta-diff-add", "Updated preview", "#d7f5dd", "none"],
  [".asta-diff-del", "Dev container", "#ffd7d5", "line-through"],
]) {
  const marks = [...document.querySelectorAll(selector)];
  assert.ok(marks.length, `LaTeXML produced no ${selector} marks`);
  assert.ok(marks.some((mark) => mark.textContent.includes(text)), `${selector} has no ${text} text`);
  for (const mark of marks) {
    const matched = rules.filter((rule) => mark.matches(rule.selectorText));
    assert.ok(matched.some((rule) => rule.style.background === background), `${selector} background missing: ${mark.outerHTML}`);
    assert.ok(matched.some((rule) => rule.style["text-decoration"] === decoration), `${selector} decoration missing: ${mark.outerHTML}`);
  }
}
for (const [selector, prefix, formatted, suffix, math] of [
  [".asta-diff-add", "Mixed addition", "bold addition", "addition tail.", "a=3"],
  [".asta-diff-del", "Mixed deletion", "italic deletion", "deletion tail.", "b=4"],
]) {
  const mark = [...document.querySelectorAll(selector)].find(
    (element) => element.textContent.includes(prefix),
  );
  assert.ok(mark, `${selector} has no mixed text/math mark`);
  assert.ok(mark.textContent.includes(formatted), `${selector} lost formatted text: ${mark.outerHTML}`);
  assert.ok(mark.textContent.includes(suffix), `${selector} leaves trailing text unmarked: ${mark.outerHTML}`);
  const formula = mark.querySelector("math");
  assert.ok(formula, `${selector} leaves inline math unmarked: ${mark.outerHTML}`);
  assert.equal(formula.getAttribute("alttext"), math, `${selector} changed the inline math`);
}
for (const selector of [".ltx_figure .ltx_caption", ".ltx_table .ltx_caption"]) {
  const caption = document.querySelector(selector);
  assert.ok(caption, `LaTeXML produced no ${selector}`);
  assert.ok(caption.querySelector(".asta-diff-add"), `${selector} addition is unmarked: ${caption.outerHTML}`);
  assert.ok(caption.querySelector(".asta-diff-del"), `${selector} deletion is unmarked: ${caption.outerHTML}`);
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
