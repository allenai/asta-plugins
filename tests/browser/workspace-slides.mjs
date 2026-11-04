// Exercise actual Quarto output, including standalone/offline use.
import assert from "node:assert/strict";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import { chromium } from "playwright";

const site = resolve(process.argv[2] ?? "../../examples/workspace/_site");
const fixtures = resolve(process.argv[4] ?? "fixtures");
const output = resolve(process.argv[3] ?? "artifacts");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

async function open(context, path, root = site) {
  const page = await context.newPage();
  const failures = [];
  const network = [];
  page.on("pageerror", (error) => failures.push(error.stack || error.message));
  // Loading the one file, with every network request blocked, also checks fonts and math.
  await page.route(/^https?:/, (route) => { network.push(route.request().url()); return route.abort(); });
  await page.goto(`file://${join(root, path)}`);
  await page.waitForFunction(() => window.Reveal?.isReady() && document.querySelector(".asta-slides-chrome"));
  await page.evaluate(() => document.fonts.ready);
  return { page, failures, network };
}

async function geometry(page, label) {
  const metrics = await page.evaluate(() => {
    const root = Reveal.getSlidesElement().getBoundingClientRect();
    return [...document.querySelectorAll(".asta-slides-chrome, .asta-slides-chrome *")]
      // checkVisibility also excludes nodes under a display:none ancestor, which report a 0x0 box at the origin.
      .filter((node) => node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }))
      .map((node) => {
        const box = node.getBoundingClientRect();
        return { element: node.className || node.tagName, x: box.x, y: box.y, width: box.width, height: box.height,
          inside: box.left >= root.left - 1 && box.top >= root.top - 1 && box.right <= root.right + 1 && box.bottom <= root.bottom + 1 };
      });
  });
  assert.ok(metrics.length >= 2, "Geometry check must inspect the chrome and its children");
  for (const metric of metrics) assert.ok(metric.inside, `${label}: ${JSON.stringify(metric)} must fit inside the slide`);
  return metrics;
}

async function lastSlide(page) {
  await page.evaluate(() => {
    const indices = Reveal.getIndices(Reveal.getSlides().at(-1));
    Reveal.slide(indices.h, indices.v);
  });
}

try {
  for (const viewport of [{ width: 1024, height: 768 }, { width: 1600, height: 900 }, { width: 2100, height: 900 }, { width: 600, height: 1000 }]) {
    const context = await browser.newContext({ viewport });
    const { page, failures, network } = await open(context, "slides/attention/slides.html");
    const loaded = await page.evaluate(async () => {
      const faces = await document.fonts.load('24px Manrope');
      return faces.length && faces.every((face) => face.status === "loaded");
    });
    assert.ok(loaded, "Bundled font must load offline");
    assert.equal(await page.locator(".slide-menu-button:visible, .progress:visible").count(), 0, "Default deck UI must stay inside the slide");
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
      const actual = await page.locator(".asta-slides-section .current").allTextContents();
      assert.deepEqual(actual, expected ? [expected] : [], "Section headline must highlight the current heading");
      if (expected) {
        assert.equal(await page.locator(".asta-slides-section > span").count(), 3, "Section headline must list every section");
        const offset = await page.evaluate(() => {
          const title = Reveal.getCurrentSlide().querySelector(":scope > h2");
          if (!title || Reveal.getCurrentSlide().classList.contains("center")) return 0;
          return title.getBoundingClientRect().left - document.querySelector(".asta-slides-section").getBoundingClientRect().left;
        });
        assert.ok(Math.abs(offset) <= 2, `Section headline must line up with the slide title (off by ${offset}px)`);
      }
      slides.push(await geometry(page, `${viewport.width}x${viewport.height} slide ${index}`));
    }
    assert.equal(await page.locator(".controls:visible").count(), 0, "Quarto's default controls: auto hides arrows for this standalone talk");
    await page.evaluate(() => {
      const slide = Reveal.getSlides().find((slide) => slide.classList.contains("dim-previous"));
      const indices = Reveal.getIndices(slide);
      Reveal.slide(indices.h, indices.v, -1);
      Reveal.nextFragment(); Reveal.nextFragment();
    });
    await page.waitForTimeout(300); // let Reveal finish fragment opacity transitions
    assert.equal(await page.locator(".dim-previous .fragment").first().evaluate((node) => getComputedStyle(node).opacity), "0.3");
    assert.equal(await page.locator(".dim-previous .current-fragment").evaluate((node) => getComputedStyle(node).opacity), "1");
    await page.evaluate(() => Reveal.toggleOverview(true));
    assert.equal(await page.locator(".asta-slides-chrome:visible").count(), 0, "Chrome must be hidden in overview mode");
    await page.evaluate(() => Reveal.toggleOverview(false));
    await page.screenshot({ path: join(output, `slides-${viewport.width}x${viewport.height}.png`) });
    assert.deepEqual(failures, [], "No script errors in the standalone deck");
    assert.deepEqual(network, [], "Standalone font/math rendering must not request a remote resource");
    assert.equal(await page.locator(".katex-error, .MathJax_Error, .MathJax_Error_Message, mjx-merror").count(), 0, "Math must typeset without errors");
    results.push({ viewport, slides });
    await context.close();
  }
  for (const name of ["no-sections", "disabled", "custom", "rich-content", "current", "controls", "header-off", "transition", "scalar-options", "no-dividers"]) {
    const context = await browser.newContext();
    const { page, failures } = await open(context, `${name}.html`, fixtures);
    if (name === "no-sections") assert.equal(await page.locator(".asta-slides-section").count(), 0);
    if (name === "disabled") {
      assert.equal(await page.locator(".asta-slides-section, .controls:visible, .slide-number:visible").count(), 0);
      assert.equal(await page.locator("body.asta-slides-dim-enabled").count(), 0);
      await lastSlide(page);
      const padding = await page.evaluate(() => getComputedStyle(Reveal.getCurrentSlide()).paddingTop);
      assert.equal(padding, "64px", "Hiding the section line must preserve title spacing");
      assert.equal(await page.locator("body").evaluate((node) => getComputedStyle(node).backgroundColor), "rgb(255, 255, 255)");
      assert.equal(await page.locator(".reveal").evaluate((node) => getComputedStyle(node).color), "rgb(34, 34, 34)");
    }
    if (name === "custom") {
      assert.ok(await page.evaluate(() => window.astaCustomScript && window.astaCustomPlugin), "Deck scripts and Reveal plugins must both run");
      assert.equal(await page.locator(".controls").evaluate((node) => getComputedStyle(node).color), "rgb(255, 163, 28)");
    }
    if (name === "no-dividers") {
      assert.equal(await page.evaluate(() => Reveal.getTotalSlides()), 4, "section-slides: false must drop divider slides at build time");
      // Quarto's own title slide keeps its `h1.title`; only `#` divider slides must be gone.
      assert.equal(await page.locator(".reveal .slides section.level1, .reveal .slides section h1:not(.title)").count(), 0, "No divider slide survives the build");
      await page.evaluate(() => Reveal.slide(1));
      assert.equal(await page.locator(".asta-slides-section:visible").count(), 0, "Headline hidden on an opening slide before the first section");
      await page.evaluate(() => Reveal.slide(2));
      await page.waitForTimeout(300);
      assert.equal(await page.locator(".asta-slides-section .current").textContent(), "First section");
      const style = await page.evaluate(() => {
        const [current, other] = [".asta-slides-section .current", ".asta-slides-section > span:not(.current)"].map((s) => getComputedStyle(document.querySelector(s)));
        const number = document.querySelector(".slide-number");
        return { size: current.fontSize, weight: current.fontWeight, current: current.color, other: other.color,
          number: number.textContent.trim(), numberSize: getComputedStyle(number).fontSize,
          surround: getComputedStyle(document.body).backgroundColor,
          slide: getComputedStyle(document.querySelector(".reveal .slides")).backgroundColor };
      });
      assert.equal(style.size, "18px");
      assert.equal(style.weight, "700");
      assert.notEqual(style.current, style.other, "Current section in the accent, others secondary");
      assert.equal(style.number, "3", "Slide number shows the number alone");
      assert.equal(style.numberSize, "16px");
      assert.notEqual(style.surround, style.slide, "The slide must stand out from its surround");
      await page.screenshot({ path: join(output, "no-dividers.png") });
    }
    if (name === "current") {
      await lastSlide(page);
      assert.equal(await page.locator(".asta-slides-section").textContent(), "Second section");
      assert.equal(await page.locator(".asta-slides-section > span").count(), 0);
    }
    if (name === "header-off" || name === "transition") {
      await page.evaluate(() => {
        const indices = Reveal.getIndices(Reveal.getSlides().find((slide) => slide.querySelector("h2")));
        Reveal.slide(indices.h, indices.v);
      });
      await page.waitForTimeout(1000);
      assert.equal(await page.evaluate(() => getComputedStyle(Reveal.getCurrentSlide()).paddingTop), "64px");
      if (name === "header-off") assert.equal(await page.locator(".asta-slides-section").count(), 0);
      else {
        const offset = await page.evaluate(() => Reveal.getCurrentSlide().querySelector("h2").getBoundingClientRect().left - document.querySelector(".asta-slides-section").getBoundingClientRect().left);
        assert.ok(Math.abs(offset) <= 2, `Section line must align after a slide transition (${offset}px)`);
      }
    }
    if (name === "controls") {
      for (const viewport of [{ width: 1024, height: 768 }, { width: 2100, height: 900 }]) {
        await page.setViewportSize(viewport);
        await page.evaluate(() => Reveal.slide(1));
        await page.waitForTimeout(100);
        const overlaps = await page.evaluate(() => {
          const number = document.querySelector(".slide-number").getBoundingClientRect();
          return [...document.querySelectorAll(".controls button")]
            .filter((button) => button.checkVisibility({ checkOpacity: true }))
            .map((button) => button.getBoundingClientRect())
            .filter((box) => box.left < number.right && number.left < box.right && box.top < number.bottom && number.top < box.bottom).length;
        });
        assert.equal(overlaps, 0, `${viewport.width}x${viewport.height}: arrows must not cover the slide number`);
        await geometry(page, `controls ${viewport.width}x${viewport.height}`);
      }
      await page.evaluate(() => Reveal.slide(0));
      await page.locator(".controls .navigate-right").click();
      assert.ok(await page.evaluate(() => Reveal.getIndices().h > 0), "Moved native controls must navigate");
    }
    if (name === "rich-content") {
      await page.evaluate(() => { const indices = Reveal.getIndices(Reveal.getSlides().find((slide) => slide.querySelector("table"))); Reveal.slide(indices.h, indices.v); });
      const contrast = await page.evaluate(() => {
        function rgb(value) { return value.match(/[\d.]+/g).map(Number); }
        function luminance(rgb) { return rgb.slice(0, 3).map((x) => { x /= 255; return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; }).reduce((a, x, i) => a + x * [0.2126, 0.7152, 0.0722][i], 0); }
        return [...document.querySelectorAll(".slide pre code, .slide pre code span, .slide table th, .slide table td, .slide .callout-body p, .slide .callout-title, .slide blockquote, .author, .date")]
          .filter((node) => node.textContent.trim())
          .map((node) => {
            let background = rgb(getComputedStyle(document.body).backgroundColor);
            for (const ancestor of [...function* () { for (let p = node; p && p !== document.body; p = p.parentElement) yield p; }()].reverse()) {
              const color = rgb(getComputedStyle(ancestor).backgroundColor);
              const alpha = color[3] ?? 1;
              background = color.slice(0, 3).map((x, i) => x * alpha + background[i] * (1 - alpha));
            }
            const a = luminance(rgb(getComputedStyle(node).color)), b = luminance(background);
            return { element: node.className || node.tagName, ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) };
          });
      });
      assert.ok(contrast.length >= 10, "Inspect code, table, callout, quote and title metadata");
      for (const item of contrast) assert.ok(item.ratio >= 4.5, `Dark slide contrast: ${JSON.stringify(item)}`);
      await page.screenshot({ path: join(output, "slides-rich-content.png") });
    }
    assert.deepEqual(failures, [], `${name}: no script errors`);
    await context.close();
  }
  const printContext = await browser.newContext();
  const { page: printPage, failures: printFailures } = await open(printContext, "controls.html?print-pdf", fixtures);
  assert.equal(await printPage.locator(".asta-slides-chrome:visible").count(), 0, "Chrome must be hidden in Reveal's print-pdf mode");
  assert.deepEqual(printFailures, []);
  await printContext.close();
  // Below 435px wide Reveal switches to its scroll view; every slide must still be a panel on the surround.
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const phonePage = await phone.newPage();
  const phoneFailures = [];
  phonePage.on("pageerror", (error) => phoneFailures.push(error.stack || error.message));
  await phonePage.goto(`file://${join(site, "slides/attention/slides.html")}`);
  await phonePage.waitForFunction(() => window.Reveal?.isReady() && document.querySelector(".reveal-viewport.reveal-scroll .scroll-page section"));
  const scroll = await phonePage.evaluate(() => {
    const color = (node) => getComputedStyle(node).backgroundColor;
    return { surround: color(document.querySelector(".reveal-viewport")), slides: color(Reveal.getSlidesElement()),
      pages: [...document.querySelectorAll(".scroll-page section")].map((node) => ({ id: node.id, background: color(node) })) };
  });
  results.push({ name: "phone-scroll-view", ...scroll });
  assert.ok(scroll.pages.length >= 4, "Scroll view must lay out every slide");
  for (const slide of scroll.pages) {
    assert.equal(slide.background, "rgb(3, 38, 41)", `Scroll-view slide ${slide.id} must be painted in the theme's background`);
  }
  assert.notEqual(scroll.surround, "rgb(3, 38, 41)", "The surround must differ from the slide");
  assert.notEqual(scroll.slides, "rgb(3, 38, 41)", "In scroll view only the slides, not their container, carry the background");
  await phonePage.screenshot({ path: join(output, "slides-phone-390x844.png") });
  await phonePage.screenshot({ path: join(output, "slides-phone-390x844-full.png"), fullPage: true });
  await phonePage.evaluate(() => document.querySelector(".reveal-viewport").scrollTo(0, 2 * innerHeight));
  await phonePage.waitForTimeout(300);
  await phonePage.screenshot({ path: join(output, "slides-phone-390x844-scrolled.png") });
  assert.deepEqual(phoneFailures, [], "Phone scroll view: no script errors");
  const { page: backgroundPage, failures: backgroundFailures, network: backgroundNetwork } = await open(phone, "backgrounds.html", fixtures);
  await backgroundPage.waitForFunction(() => document.querySelector(".reveal-viewport.reveal-scroll .scroll-page section"));
  const backgrounds = await backgroundPage.evaluate(() => {
    return Reveal.getSlides().map((slide) => ({ id: slide.id,
      shorthand: slide.getAttribute("data-background"), explicit: slide.getAttribute("data-background-color"),
      panel: getComputedStyle(slide).backgroundColor,
      background: getComputedStyle(Reveal.getSlideBackground(slide)).backgroundColor }));
  });
  assert.equal(backgrounds.find((slide) => slide.id === "shorthand-background").shorthand, "#105257", "The fixture must exercise Reveal's data-background shorthand");
  for (const slide of backgrounds) {
    if (slide.shorthand || slide.explicit) {
      assert.equal(slide.panel, "rgba(0, 0, 0, 0)", `${slide.id}: the theme must not cover a custom background`);
      assert.equal(slide.background, slide.shorthand ? "rgb(16, 82, 87)" : "rgb(10, 50, 53)", `${slide.id}: Reveal must paint the custom background`);
    } else {
      assert.equal(slide.panel, "rgb(3, 38, 41)", `${slide.id}: ordinary slides must keep the theme background`);
    }
  }
  results.push({ name: "phone-custom-backgrounds", slides: backgrounds });
  await backgroundPage.locator("#shorthand-background").evaluate((node) => node.closest(".scroll-page").scrollIntoView());
  await backgroundPage.waitForTimeout(300);
  await backgroundPage.screenshot({ path: join(output, "slides-phone-custom-background.png") });
  assert.deepEqual(backgroundFailures, [], "Custom phone backgrounds: no script errors");
  assert.deepEqual(backgroundNetwork, [], "Custom phone backgrounds work offline");
  await phone.close();
  const html = await readFile(join(site, "index.html"), "utf8");
  assert.match(html, /slides\/attention\/slides\.html/, "The site must link to the talk");
  assert.match(html, />Presentation slides</, "The overview must say the link opens slides");
  assert.match(html, /Slides: Attention in sequence models/, "The sidebar must label the deck as slides");
  await writeFile(join(output, "slide-checks.json"), JSON.stringify(results, null, 2));
  console.log("Slide checks passed: offline fonts/math, section headline and alignment, controls placement, dim builds, opt-outs, SCSS/scripts/plugins, and chrome containment at four aspect ratios.");
} finally {
  await browser.close();
}
