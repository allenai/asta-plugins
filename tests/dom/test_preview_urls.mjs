import assert from "node:assert/strict";
import { test } from "node:test";
import { parseHTML } from "linkedom";
import { documentUrls } from "../browser/preview-urls.mjs";

test("preview URL scanning includes SVG anchors and root-relative resources", () => {
  const { document } = parseHTML(`<html><body>
    <a href="notes/">notes</a>
    <svg><a href="/outside.html">outside</a></svg>
    <iframe src="slides/talk/index.html"></iframe>
    <img src="image.png">
    <a href="https://example.org/">external</a>
  </body></html>`);
  const elements = [...document.querySelectorAll("a[href], iframe[src], img[src]")];
  for (const element of elements) {
    Object.defineProperty(element, "baseURI", {
      value: "https://example.test/pr-preview/pr-1/index.html",
    });
  }
  // Browsers expose an SVGAnimatedString, unlike HTMLAnchorElement.href.
  Object.defineProperty(document.querySelector("svg a"), "href", {
    value: { baseVal: "/outside.html" },
  });
  assert.deepEqual(documentUrls(elements), [
    "https://example.test/pr-preview/pr-1/notes/",
    "https://example.test/outside.html",
    "https://example.test/pr-preview/pr-1/slides/talk/index.html",
    "https://example.test/pr-preview/pr-1/image.png",
    "https://example.org/",
  ]);
});
