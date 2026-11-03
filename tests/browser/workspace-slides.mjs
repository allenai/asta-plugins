// Exercise actual Quarto output, including standalone/offline use.
import assert from "node:assert/strict";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import { chromium } from "playwright";

const site = resolve(process.argv[2] ?? "../../examples/workspace/_site");
const output = resolve(process.argv[3] ?? "artifacts");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

async function open(context, path) {
  const page = await context.newPage();
  const failures = [];
  const network = [];
  page.on("pageerror", (error) => failures.push(error.message));
  // Loading the one file, with every network request blocked, also checks fonts and math.
  await page.route(/^https?:/, (route) => { network.push(route.request().url()); return route.abort(); });
  await page.goto(`file://${join(site, path)}`);
  await page.waitForFunction(() => window.Reveal?.isReady() && document.querySelector(".asta-slides-chrome"));
  await page.evaluate(() => document.fonts.ready);
  return { page, failures, network };
}

async function geometry(page, label) {
  const metrics = await page.evaluate(() => {
    const root = Reveal.getSlidesElement().getBoundingClientRect();
    return [...document.querySelectorAll(".asta-slides-chrome, .asta-slides-chrome *")]
      .filter((node) => { const s = getComputedStyle(node); return s.display !== "none" && s.visibility !== "hidden" && Number(s.opacity) !== 0; })
      .map((node) => {
        const box = node.getBoundingClientRect();
        return { element: node.className || node.tagName, x: box.x, y: box.y, width: box.width, height: box.height,
          inside: box.left >= root.left - 1 && box.top >= root.top - 1 && box.right <= root.right + 1 && box.bottom <= root.bottom + 1 };
      });
  });
  assert.ok(metrics.length > 3, "Geometry check must inspect the chrome and its children");
  for (const metric of metrics) assert.ok(metric.inside, `${label}: ${JSON.stringify(metric)} must fit inside the slide`);
  return metrics;
}

try {
  for (const viewport of [{ width: 1024, height: 768 }, { width: 1600, height: 900 }, { width: 2100, height: 900 }, { width: 600, height: 1000 }]) {
    const context = await browser.newContext({ viewport });
    const { page, failures, network } = await open(context, "talks/attention/slides.html");
    const loaded = await page.evaluate(async () => {
      const faces = await document.fonts.load('24px Manrope');
      return faces.length && faces.every((face) => face.status === "loaded");
    });
    assert.ok(loaded, "Bundled font must load offline");
    await page.waitForFunction(() => document.querySelector(".katex, .MathJax, mjx-container"), null, { timeout: 30000 });
    const count = await page.evaluate(() => Reveal.getSlides().length);
    const slides = [];
    for (let index = 0; index < count; index++) {
      await page.evaluate((index) => { const slide = Reveal.getSlides()[index]; const indices = Reveal.getIndices(slide); Reveal.slide(indices.h, indices.v); }, index);
      await page.waitForTimeout(60);
      const expected = await page.evaluate(() => {
        let section = "";
        for (const slide of Reveal.getSlides()) {
          const heading = slide.querySelector("h1:not(.title)");
          if (heading) section = heading.textContent.trim();
          if (slide === Reveal.getCurrentSlide()) return section;
        }
      });
      const actual = await page.locator(".asta-slides-section").textContent();
      assert.equal(actual, expected, "Section label must follow the current heading");
      slides.push(await geometry(page, `${viewport.width}x${viewport.height} slide ${index}`));
    }
    await page.evaluate(() => Reveal.slide(0));
    await page.locator(".controls .navigate-right").click();
    assert.ok(await page.evaluate(() => Reveal.getIndices().h > 0), "Moved native controls must navigate");
    await page.evaluate(() => {
      const slide = Reveal.getSlides().find((slide) => slide.classList.contains("dim-previous"));
      const indices = Reveal.getIndices(slide);
      Reveal.slide(indices.h, indices.v);
      Reveal.nextFragment(); Reveal.nextFragment();
    });
    assert.equal(await page.locator(".dim-previous .fragment").first().evaluate((node) => getComputedStyle(node).opacity), "0.3");
    assert.equal(await page.locator(".dim-previous .current-fragment").evaluate((node) => getComputedStyle(node).opacity), "1");
    await page.screenshot({ path: join(output, `slides-${viewport.width}x${viewport.height}.png`) });
    assert.deepEqual(failures, [], "No script errors in the standalone deck");
    assert.deepEqual(network, [], "Standalone font/math rendering must not request a remote resource");
    assert.equal(await page.locator(".katex-error, .MathJax_Error, .MathJax_Error_Message, mjx-merror").count(), 0, "Math must typeset without errors");
    results.push({ viewport, slides });
    await context.close();
  }
  for (const name of ["no-sections", "disabled", "custom"]) {
    const context = await browser.newContext();
    const { page, failures } = await open(context, `slide-fixtures/${name}.html`);
    if (name === "no-sections") assert.equal(await page.locator(".asta-slides-section").count(), 0);
    if (name === "disabled") {
      assert.equal(await page.locator(".asta-slides-section, .controls, .slide-number").count(), 0);
      assert.equal(await page.locator("body.asta-slides-theme, body.asta-slides-dim-enabled").count(), 0);
    }
    if (name === "custom") {
      assert.ok(await page.evaluate(() => window.astaCustomScript && window.astaCustomPlugin), "Deck scripts and Reveal plugins must both run");
      assert.equal(await page.locator(".controls").evaluate((node) => getComputedStyle(node).color), "rgb(255, 163, 28)");
    }
    assert.deepEqual(failures, []);
    await context.close();
  }
  const html = await readFile(join(site, "index.html"), "utf8");
  assert.match(html, /talks\/attention\/slides\.html/, "The site must link to the talk");
  await writeFile(join(output, "slide-checks.json"), JSON.stringify(results, null, 2));
  console.log("Slide checks passed: offline fonts/math, section tracking, native controls, dim builds, opt-outs, SCSS/scripts/plugins, and chrome containment at four aspect ratios.");
} finally {
  await browser.close();
}
