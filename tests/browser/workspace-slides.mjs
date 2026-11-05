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
const customBackgroundSelector = ["background", "background-color", "background-image", "background-gradient", "background-video", "background-iframe"]
  .map((attribute) => `[data-${attribute}]`).join(",");

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

// Reveal's margin is 0, so the slide fills the largest 16:9 area of the window or frame.
async function filled(page, label) {
  const fill = await page.evaluate(() => {
    const box = Reveal.getSlidesElement().getBoundingClientRect();
    const scale = Math.min(innerWidth / 1600, innerHeight / 900);
    return { margin: Reveal.getConfig().margin, box: [box.left, box.top, box.width, box.height],
      expected: [(innerWidth - 1600 * scale) / 2, (innerHeight - 900 * scale) / 2, 1600 * scale, 900 * scale] };
  });
  assert.equal(fill.margin, 0, `${label}: the format sets margin: 0`);
  fill.box.forEach((value, index) => assert.ok(Math.abs(value - fill.expected[index]) <= 1.5,
    `${label}: the slide must fill its 16:9 area (${JSON.stringify(fill)})`));
  return fill;
}

// Content stays inside the slide's padding on the left, right and top; the chrome on every side.
async function padded(page, label) {
  const result = await page.evaluate(() => {
    const slide = Reveal.getCurrentSlide();
    const scale = Reveal.getScale();
    const root = Reveal.getSlidesElement().getBoundingClientRect();
    const pad = parseFloat(getComputedStyle(slide).paddingLeft);
    const inner = { left: root.left + pad * scale, right: root.right - pad * scale, top: root.top + pad * scale, bottom: root.bottom - pad * scale };
    const visible = (node) => node.checkVisibility({ checkVisibilityCSS: true }) && node.getBoundingClientRect().width > 0;
    const outside = [];
    for (const [nodes, bottom] of [[[...slide.children], false], [[...document.querySelectorAll(".asta-slides-chrome > *")], true]]) {
      for (const node of nodes.filter(visible)) {
        const box = node.getBoundingClientRect();
        if (box.left < inner.left - 2 || box.right > inner.right + 2 || box.top < inner.top - 2 || (bottom && box.bottom > inner.bottom + 2)) {
          outside.push({ element: node.className || node.tagName, box: [box.left, box.top, box.right, box.bottom], inner });
        }
      }
    }
    return { pad, outside };
  });
  assert.equal(result.pad, 48, `${label}: slides have the default 48px padding`);
  assert.deepEqual(result.outside, [], `${label}: the headline, number and content must sit inside the padding`);
}

async function contentSlide(page) {
  await page.evaluate(() => {
    const slide = Reveal.getSlides().find((slide) => slide.querySelector(":scope > h2") && !slide.classList.contains("center"));
    const indices = Reveal.getIndices(slide);
    Reveal.slide(indices.h, indices.v);
  });
  await page.waitForTimeout(300);
}

async function lastSlide(page) {
  await page.evaluate(() => {
    const indices = Reveal.getIndices(Reveal.getSlides().at(-1));
    Reveal.slide(indices.h, indices.v);
  });
}

async function scrollToSlide(page, index) {
  await page.evaluate((index) => document.querySelectorAll(".scroll-page-content > section")[index].closest(".scroll-page").scrollIntoView({ behavior: "instant", block: "center" }), index);
  await page.waitForFunction((index) => Reveal.getCurrentSlide() === document.querySelectorAll(".scroll-page-content > section")[index], index);
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
    const fill = await filled(page, `${viewport.width}x${viewport.height}`);
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
      await padded(page, `${viewport.width}x${viewport.height} slide ${index}`);
    }
    await contentSlide(page);
    await page.screenshot({ path: join(output, `slides-${viewport.width}x${viewport.height}-content.png`) });
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
    results.push({ viewport, fill, slides });
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
      assert.equal(padding, "88px", "Hiding the section line must preserve title spacing");
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
      assert.equal(await page.evaluate(() => getComputedStyle(Reveal.getCurrentSlide()).paddingTop), "88px");
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
  // Below Reveal's scrollActivationWidth, every ordinary slide must still be a panel on the surround.
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const phonePage = await phone.newPage();
  const phoneFailures = [];
  phonePage.on("pageerror", (error) => phoneFailures.push(error.stack || error.message));
  await phonePage.goto(`file://${join(site, "slides/attention/slides.html")}`);
  await phonePage.waitForFunction(() => window.Reveal?.isReady() && document.querySelector(".reveal-viewport.reveal-scroll .scroll-page-content > section"));
  const scroll = await phonePage.evaluate((customBackgroundSelector) => {
    const color = (node) => getComputedStyle(node).backgroundColor;
    return { surround: color(document.querySelector(".reveal-viewport")), slides: color(Reveal.getSlidesElement()),
      pages: [...document.querySelectorAll(".scroll-page-content > section")].map((node) => ({ id: node.id, custom: node.matches(customBackgroundSelector), background: color(node) })) };
  }, customBackgroundSelector);
  results.push({ name: "phone-scroll-view", ...scroll });
  assert.ok(scroll.pages.length >= 4, "Scroll view must lay out every slide");
  for (const slide of scroll.pages) {
    assert.equal(slide.background, slide.custom ? "rgba(0, 0, 0, 0)" : "rgb(3, 38, 41)", `Scroll-view slide ${slide.id} must preserve its custom or theme background`);
  }
  assert.notEqual(scroll.surround, "rgb(3, 38, 41)", "The surround must differ from the slide");
  assert.notEqual(scroll.slides, "rgb(3, 38, 41)", "In scroll view only the slides, not their container, carry the background");
  await phonePage.screenshot({ path: join(output, "slides-phone-390x844.png") });
  await phonePage.screenshot({ path: join(output, "slides-phone-390x844-full.png"), fullPage: true });
  await scrollToSlide(phonePage, 2);
  await phonePage.screenshot({ path: join(output, "slides-phone-390x844-scrolled.png") });
  assert.deepEqual(phoneFailures, [], "Phone scroll view: no script errors");
  const { page: backgroundPage, failures: backgroundFailures, network: backgroundNetwork } = await open(phone, "backgrounds.html", fixtures);
  await backgroundPage.waitForFunction(() => document.querySelector(".reveal-viewport.reveal-scroll .scroll-page-content > section"));
  await backgroundPage.evaluate(() => {
    // Simulate nested content added by a deck script after Reveal has classified slide stacks.
    const content = document.querySelector("#shorthand-background h3").nextElementSibling;
    const nested = document.createElement("section");
    nested.className = "custom-background-detail";
    // Keep ordinary content geometry rather than Reveal's positioning for nested slide sections.
    nested.style.cssText = "position:static!important;width:auto!important;height:auto!important;top:auto!important;left:auto!important;transform:none!important";
    content.replaceWith(nested);
    nested.appendChild(content);
  });
  const backgrounds = await backgroundPage.evaluate((customBackgroundSelector) => {
    return [...document.querySelectorAll(".scroll-page-content > section")].map((slide) => ({ id: slide.id,
      custom: slide.matches(customBackgroundSelector),
      shorthand: slide.getAttribute("data-background"), explicit: slide.getAttribute("data-background-color"),
      panel: getComputedStyle(slide).backgroundColor,
      nested: [...slide.querySelectorAll("section")].map((node) => ({ id: node.id || node.className, background: getComputedStyle(node).backgroundColor })),
      background: getComputedStyle(Reveal.getSlideBackground(slide)).backgroundColor }));
  }, customBackgroundSelector);
  assert.equal(backgrounds.find((slide) => slide.id === "shorthand-background").shorthand, "#105257", "The fixture must exercise Reveal's data-background shorthand");
  assert.ok(backgrounds.find((slide) => slide.id === "shorthand-background").nested.length > 0, "The custom-background fixture must contain a nested section");
  for (const slide of backgrounds) {
    if (slide.custom) {
      assert.equal(slide.panel, "rgba(0, 0, 0, 0)", `${slide.id}: the theme must not cover a custom background`);
      assert.equal(slide.background, slide.shorthand ? "rgb(16, 82, 87)" : "rgb(10, 50, 53)", `${slide.id}: Reveal must paint the custom background`);
      for (const nested of slide.nested) assert.equal(nested.background, "rgba(0, 0, 0, 0)", `${slide.id}: nested section ${nested.id} must not cover the custom background`);
    } else {
      assert.equal(slide.panel, "rgb(3, 38, 41)", `${slide.id}: ordinary slides must keep the theme background`);
    }
  }
  results.push({ name: "phone-custom-backgrounds", slides: backgrounds });
  await scrollToSlide(backgroundPage, 1);
  await backgroundPage.screenshot({ path: join(output, "slides-phone-custom-background.png") });
  assert.deepEqual(backgroundFailures, [], "Custom phone backgrounds: no script errors");
  assert.deepEqual(backgroundNetwork, [], "Custom phone backgrounds work offline");
  const { page: verticalPage, failures: verticalFailures, network: verticalNetwork } = await open(phone, "vertical-backgrounds.html", fixtures);
  await verticalPage.waitForFunction(() => document.querySelector(".reveal-viewport.reveal-scroll .scroll-page-content > section"));
  async function verticalBackgrounds() {
    return verticalPage.evaluate(() => [...document.querySelectorAll(".scroll-page-content > section")]
      .filter((slide) => /^(inherited|ordinary)-/.test(slide.id))
      .map((slide) => ({ id: slide.id, ownBackground: slide.hasAttribute("data-background"),
        inherited: slide.classList.contains("asta-slides-inherited-background"),
        panel: getComputedStyle(slide).backgroundColor,
        page: getComputedStyle(slide.closest(".scroll-page")).backgroundColor })));
  }
  function checkVerticalBackgrounds(slides) {
    assert.equal(slides.length, 4, "Fixture must render both vertical stacks as four actual slide panels");
    for (const slide of slides) {
      const inherited = slide.id.startsWith("inherited-");
      assert.equal(slide.ownBackground, false, `${slide.id}: background must come from its parent stack`);
      assert.equal(slide.inherited, inherited, `${slide.id}: only custom-background stacks opt out of the theme panel`);
      assert.equal(slide.panel, inherited ? "rgba(0, 0, 0, 0)" : "rgb(3, 38, 41)", `${slide.id}: preserve inherited or theme background`);
      if (inherited) assert.equal(slide.page, "rgb(35, 62, 88)", `${slide.id}: Reveal must carry the stack color to its scroll page`);
    }
  }
  const verticalSlides = await verticalBackgrounds();
  checkVerticalBackgrounds(verticalSlides);
  results.push({ name: "phone-vertical-backgrounds", slides: verticalSlides });
  // Reveal restores its original slide HTML when leaving scroll view. The
  // inherited-background markers must still work when it enters scroll view again.
  await verticalPage.setViewportSize({ width: 1024, height: 768 });
  await verticalPage.waitForFunction(() => !Reveal.isScrollView());
  await verticalPage.setViewportSize({ width: 390, height: 844 });
  await verticalPage.waitForFunction(() => Reveal.isScrollView());
  checkVerticalBackgrounds(await verticalBackgrounds());
  const inheritedIndex = await verticalPage.evaluate(() => [...document.querySelectorAll(".scroll-page-content > section")].findIndex((slide) => slide.id === "inherited-two"));
  await scrollToSlide(verticalPage, inheritedIndex);
  await verticalPage.screenshot({ path: join(output, "slides-phone-vertical-background.png") });
  assert.deepEqual(verticalFailures, [], "Vertical phone backgrounds: no script errors");
  assert.deepEqual(verticalNetwork, [], "Vertical phone backgrounds work offline");
  const { page: classPage, failures: classFailures, network: classNetwork } = await open(phone, "background-classes.html", fixtures);
  await classPage.waitForFunction(() => document.querySelector(".reveal-viewport.reveal-scroll .scroll-page-content > section.class-background"));
  const classBackground = await classPage.locator("section.class-background").evaluate((slide) => ({
    color: getComputedStyle(slide).backgroundColor, image: getComputedStyle(slide).backgroundImage,
    ownBackground: slide.hasAttribute("data-background") || slide.hasAttribute("data-background-color")
  }));
  assert.equal(classBackground.ownBackground, false, "Class fixture must use deck CSS, not Reveal background attributes");
  assert.equal(classBackground.color, "rgb(23, 62, 68)", "A deck CSS class must override the theme panel color");
  assert.match(classBackground.image, /linear-gradient/, "The theme must not reset a deck CSS background image");
  results.push({ name: "phone-class-background", ...classBackground });
  const classIndex = await classPage.evaluate(() => [...document.querySelectorAll(".scroll-page-content > section")].findIndex((slide) => slide.classList.contains("class-background")));
  await scrollToSlide(classPage, classIndex);
  await classPage.screenshot({ path: join(output, "slides-phone-class-background.png") });
  assert.deepEqual(classFailures, [], "Class-styled phone background: no script errors");
  assert.deepEqual(classNetwork, [], "Class-styled phone background works offline");
  await phone.close();
  // The deck's viewer page: the deck plays at 16:9 inside the site, with expand and Esc.
  const viewerContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const viewer = await viewerContext.newPage();
  const viewerFailures = [];
  viewer.on("pageerror", (error) => viewerFailures.push(error.stack || error.message));
  await viewer.goto(`file://${join(site, "slides/attention/index.html")}`);
  await viewer.waitForSelector("[data-deck-viewer] .deck-frame");
  await viewer.waitForFunction(() => parseFloat(document.querySelector(".deck-frame").style.width) > 0);
  const inSite = await viewer.evaluate(() => {
    const frame = document.querySelector(".deck-frame").getBoundingClientRect();
    const sidebar = document.querySelector("#quarto-sidebar");
    return {
      title: document.querySelector(".deck-title").textContent,
      where: document.querySelector(".deck-where").textContent,
      popout: (() => {
        const link = document.querySelector(".deck-popout");
        return link && { href: link.getAttribute("href"), title: link.title, label: link.getAttribute("aria-label"),
          text: link.textContent.trim(), icon: Boolean(link.querySelector("svg")), target: link.target };
      })(),
      present: Boolean(document.querySelector(".deck-present")),
      outline: getComputedStyle(document.querySelector(".deck-frame")).boxShadow,
      border: (() => {
        const probe = document.createElement("span");
        probe.style.color = "var(--bs-border-color)";
        document.body.append(probe);
        const color = getComputedStyle(probe).color;
        probe.remove();
        return color;
      })(),
      src: document.querySelector(".deck-frame").getAttribute("src"),
      sidebar: Boolean(sidebar && sidebar.getBoundingClientRect().width > 0 && getComputedStyle(sidebar).display !== "none"),
      ratio: frame.width / frame.height, top: frame.top, bottom: frame.bottom, left: frame.left, right: frame.right,
      viewport: [innerWidth, innerHeight]
    };
  });
  assert.equal(inSite.title, "Attention in sequence models", "The viewer bar names the deck");
  assert.match(inSite.where, /Written in slides\/attention\/slides\.qmd/, "The viewer bar says where the deck is written");
  assert.equal(inSite.present, false, "The Present text link is gone");
  assert.ok(inSite.popout, "The bar has a pop-out button");
  assert.equal(inSite.popout.title, "Open the slides on their own", "The pop-out is titled");
  assert.equal(inSite.popout.label, "Open the slides on their own", "The pop-out has an accessible name");
  assert.deepEqual([inSite.popout.text, inSite.popout.icon, inSite.popout.target], ["", true, "_blank"], "The pop-out is an icon that opens a new tab");
  assert.match(inSite.popout.href, /^slides\.html(#\/.*)?$/, "The pop-out opens the deck alone");
  assert.ok(inSite.outline.startsWith(inSite.border) && inSite.outline.includes("0px 0px 0px 1px"),
    `The frame has a thin outline in the theme's border colour (got ${inSite.outline}, border ${inSite.border})`);
  assert.equal(inSite.src, "slides.html", "The viewer plays the deck in place");
  assert.ok(inSite.sidebar, "The viewer page shows the site's sidebar");
  assert.ok(Math.abs(inSite.ratio - 16 / 9) < 0.01, `The deck plays at 16:9 (got ${inSite.ratio})`);
  assert.ok(inSite.top >= 0 && inSite.bottom <= inSite.viewport[1] + 0.5 && inSite.right <= inSite.viewport[0] + 0.5, "A whole slide is in view");
  await viewer.waitForFunction(() => document.querySelector(".deck-frame").contentDocument === null
    || document.querySelector(".deck-frame").contentDocument.querySelector(".reveal .slides section"));
  await viewer.screenshot({ path: join(output, "deck-viewer.png") });
  results.push({ name: "deck-viewer", ...inSite });
  // A dark theme whose inline code is a white box: the bar's path must still read.
  const barCode = await viewer.evaluate(() => {
    const style = document.createElement("style");
    style.textContent = "body { color: rgb(230, 230, 230); } body code:not(.sourceCode) { color: rgb(245, 245, 245); background-color: rgb(255, 255, 255); }";
    document.head.append(style);
    const code = getComputedStyle(document.querySelector(".deck-where code"));
    const where = getComputedStyle(document.querySelector(".deck-where"));
    const result = { color: code.color, barColor: where.color, background: code.backgroundColor };
    style.remove();
    return result;
  });
  assert.equal(barCode.color, barCode.barColor, "The bar's code takes the bar's text colour on any theme");
  assert.equal(barCode.background, "rgba(0, 0, 0, 0)", "The bar's code draws no box of its own");
  // On file:// the frame isn't same-origin: keys reach the deck by message, and the
  // pop-out follows the slide the deck reports. Focus stays on the page throughout.
  const popoutHref = () => viewer.evaluate(() => document.querySelector(".deck-popout").getAttribute("href"));
  await viewer.waitForFunction(() => document.querySelector(".deck-popout").getAttribute("href").startsWith("slides.html#/"));
  await viewer.evaluate(() => document.activeElement?.blur());
  const firstHref = await popoutHref();
  await viewer.keyboard.press("End");
  await viewer.waitForFunction((first) => document.querySelector(".deck-popout").getAttribute("href") !== first, firstHref);
  const lastHref = await popoutHref();
  await viewer.keyboard.press("Home");
  await viewer.waitForFunction((first) => document.querySelector(".deck-popout").getAttribute("href") === first, firstHref);
  assert.ok(await viewer.evaluate(() => document.activeElement === document.body), "Keys moved the deck with focus on the page");
  results.push({ name: "deck-viewer-file-keys", firstHref, lastHref });
  await viewer.click(".deck-expand");
  const expanded = await viewer.evaluate(() => {
    const host = document.querySelector("[data-deck-viewer]").getBoundingClientRect();
    const frame = document.querySelector(".deck-frame").getBoundingClientRect();
    return {
      pressed: document.querySelector(".deck-expand").getAttribute("aria-pressed"),
      sidebarHidden: getComputedStyle(document.querySelector("#quarto-sidebar")).display === "none",
      host: [host.left, host.top, host.width, host.height], frameWidth: frame.width,
      viewport: [innerWidth, innerHeight]
    };
  });
  assert.equal(expanded.pressed, "true", "Expand is pressed");
  assert.ok(expanded.sidebarHidden, "Expanded, the site's sidebar gives way");
  assert.deepEqual(expanded.host, [0, 0, ...expanded.viewport], "Expanded, the viewer takes the whole window");
  assert.ok(expanded.frameWidth > inSite.right - inSite.left, "Expanded, the deck grows");
  await viewer.screenshot({ path: join(output, "deck-viewer-expanded.png") });
  await viewer.locator(".deck-title").click();
  await viewer.keyboard.press("Escape");
  const restored = await viewer.evaluate(() => ({
    pressed: document.querySelector(".deck-expand").getAttribute("aria-pressed"),
    sidebar: getComputedStyle(document.querySelector("#quarto-sidebar")).display !== "none"
  }));
  assert.deepEqual(restored, { pressed: "false", sidebar: true }, "Esc gives the site back");
  assert.deepEqual(viewerFailures, [], "Deck viewer: no script errors");
  results.push({ name: "deck-viewer-expand", expanded, restored });
  // Collapsing consumes Esc: nothing after the viewer's capture listener sees it.
  await viewer.evaluate(() => { window.leakedKeys = []; document.addEventListener("keydown", (event) => window.leakedKeys.push(event.key)); });
  await viewer.click(".deck-expand");
  await viewer.locator(".deck-title").click();
  await viewer.keyboard.press("Escape");
  const consumed = await viewer.evaluate(() => ({ leaked: window.leakedKeys, pressed: document.querySelector(".deck-expand").getAttribute("aria-pressed") }));
  assert.deepEqual(consumed, { leaked: [], pressed: "false" }, "Collapsing the viewer consumes Esc");
  // A scrolled page sizes the deck as an unscrolled one does.
  const unscrolled = await viewer.evaluate(() => document.querySelector(".deck-frame").style.width);
  const scrolled = await viewer.evaluate(async () => {
    document.body.style.paddingBottom = "3000px";
    scrollTo(0, 150);
    dispatchEvent(new Event("scroll"));
    dispatchEvent(new Event("resize"));
    await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
    return { width: document.querySelector(".deck-frame").style.width, scrollY };
  });
  assert.ok(scrolled.scrollY > 0, "The page scrolled");
  assert.equal(scrolled.width, unscrolled, "Scrolling the page doesn't resize the deck");
  results.push({ name: "deck-viewer-esc-scroll", consumed, unscrolled, scrolled });
  // A short window: the frame fits the height left below the bar, so a whole slide
  // stays in view, down to the 180 px floor (Reveal's minScale of a 900 px slide);
  // below it the frame stops shrinking and the page scrolls.
  const shortFit = async (room) => {
    await viewer.setViewportSize({ width: 1280, height: 800 });
    await viewer.goto(`file://${join(site, "slides/attention/index.html")}`);
    await viewer.waitForFunction(() => parseFloat(document.querySelector(".deck-frame").style.width) > 0);
    const top = await viewer.evaluate(() => document.querySelector(".deck-stage").getBoundingClientRect().top + scrollY);
    await viewer.setViewportSize({ width: 1280, height: Math.ceil(top + 16 + room) });
    await viewer.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
    const deck = await (await viewer.$(".deck-frame")).contentFrame();
    await deck.waitForFunction(() => window.Reveal?.isReady());
    await deck.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
    await viewer.waitForTimeout(300);
    const content = await deck.evaluate(() => {
      const slide = Reveal.getCurrentSlide();
      const parts = [...slide.querySelectorAll("h1, h2, h3, p, li, img, figure, pre, table")]
        .filter((element) => element.checkVisibility({ opacityProperty: true, visibilityProperty: true }))
        .map((element) => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 40), ...element.getBoundingClientRect().toJSON() }))
        .filter((box) => box.width > 0 && box.height > 0);
      const outside = parts.filter((box) => box.left < -0.5 || box.top < -0.5 || box.right > innerWidth + 0.5 || box.bottom > innerHeight + 0.5);
      return { width: innerWidth, height: innerHeight, scale: Reveal.getScale(), scrollView: Reveal.isScrollView?.() ?? false, count: parts.length, outside };
    });
    const frame = await viewer.evaluate(() => {
      const frame = document.querySelector(".deck-frame").getBoundingClientRect();
      return { top: frame.top, bottom: frame.bottom, height: frame.height, ratio: frame.width / frame.height,
        viewport: innerHeight, scrolls: document.documentElement.scrollHeight > innerHeight };
    });
    return { ...frame, content };
  };
  const short = await shortFit(180);
  assert.ok(Math.abs(short.height - 180) < 1.5, `A short window fits the frame to the floor (got ${short.height})`);
  assert.ok(Math.abs(short.ratio - 16 / 9) < 0.01, `The short frame stays 16:9 (got ${short.ratio})`);
  assert.ok(short.top >= 0 && short.bottom <= short.viewport + 0.5, "At the floor the whole frame is in view");
  assert.ok(short.content.count > 0, "The deck's first slide has content to check");
  assert.deepEqual(short.content.outside, [], `At the floor the slide's content stays inside its frame (${JSON.stringify(short.content)})`);
  await viewer.screenshot({ path: join(output, "deck-viewer-short.png") });
  const tiny = await shortFit(80);
  assert.ok(Math.abs(tiny.height - 180) < 1.5, `Below the floor the frame stops shrinking (got ${tiny.height})`);
  assert.ok(tiny.scrolls, "Below the floor the page scrolls");
  assert.deepEqual(tiny.content.outside, [], "Below the floor the slide's content stays inside its frame");
  results.push({ name: "deck-viewer-short", short, tiny });
  assert.deepEqual(viewerFailures, [], "Deck viewer: no script errors after the short-window checks");
  await viewerContext.close();
  // Served from one origin, Esc pressed inside the deck collapses the viewer
  // without also opening Reveal's overview.
  const servedContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await servedContext.route(/^https?:/, (route) => {
    const url = new URL(route.request().url());
    if (url.host !== "deck.test") return route.abort();
    return route.fulfill({ path: join(site, decodeURIComponent(url.pathname)) });
  });
  const served = await servedContext.newPage();
  await served.goto("http://deck.test/slides/attention/index.html");
  await served.waitForFunction(() => document.querySelector(".deck-frame").contentWindow?.Reveal?.isReady?.());
  const framed = served.frames().find((frame) => frame !== served.mainFrame());
  await framed.waitForFunction(() => document.querySelector(".asta-slides-chrome"));
  const frameFill = await filled(framed, "viewer frame");
  assert.ok(Math.abs(frameFill.box[0]) <= 1.5 && Math.abs(frameFill.box[1]) <= 1.5, "In the 16:9 viewer frame, the slide shows no surround");
  await contentSlide(framed);
  await padded(framed, "viewer frame");
  await served.screenshot({ path: join(output, "deck-viewer-content.png") });
  results.push({ name: "deck-viewer-frame", ...frameFill });
  await framed.evaluate(() => Reveal.slide(0, 0));
  // Reveal's navigation keys, pressed with focus on the page, never in the frame.
  await served.evaluate(() => document.activeElement?.blur());
  const indices = () => framed.evaluate(() => JSON.stringify(Reveal.getIndices()));
  const keySteps = [];
  for (const key of ["ArrowRight", "PageDown", "Space", "ArrowLeft", "PageUp", "End", "Home"]) {
    const before = await indices();
    await served.keyboard.press(key);
    await framed.waitForFunction((previous) => JSON.stringify(Reveal.getIndices()) !== previous, before, { timeout: 5000 });
    keySteps.push({ key, before, after: await indices() });
    if (key === "End") {
      // Reveal's own End goes to the last section's stack, not the stack's last slide.
      assert.ok(await framed.evaluate(() => Reveal.getIndices().h === Reveal.getHorizontalSlides().length - 1),
        "End goes to the last section, as in the deck alone");
      await served.waitForFunction(() => document.querySelector(".deck-popout").getAttribute("href")
        === "slides.html" + document.querySelector(".deck-frame").contentWindow.location.hash);
      await served.screenshot({ path: join(output, "deck-viewer-keys.png") });
      // The pop-out opens the deck alone in a new tab, at the slide the viewer is on.
      const atSlide = await framed.evaluate(() => JSON.stringify(Reveal.getIndices()));
      const [tab] = await Promise.all([servedContext.waitForEvent("page"), served.click(".deck-popout")]);
      await tab.waitForFunction(() => window.Reveal?.isReady?.());
      const opened = { url: tab.url(), indices: await tab.evaluate(() => JSON.stringify(Reveal.getIndices())) };
      assert.match(opened.url, /^http:\/\/deck\.test\/slides\/attention\/slides\.html#\//, "The pop-out opens slides.html alone");
      assert.equal(opened.indices, atSlide, "The pop-out opens at the viewer's slide");
      await tab.close();
      results.push({ name: "deck-viewer-popout", ...opened });
      await served.evaluate(() => document.activeElement?.blur());
    }
  }
  assert.ok(await framed.evaluate(() => Reveal.getIndices().h === 0 && Reveal.getIndices().v === 0), "Home goes to the first slide");
  assert.ok(await served.evaluate(() => !document.querySelector(".deck-frame").contains(document.activeElement) && document.activeElement !== document.querySelector(".deck-frame")), "The frame never took focus");
  // A text field keeps its keys.
  await served.evaluate(() => { const field = document.createElement("input"); field.id = "key-field"; document.body.append(field); field.focus(); });
  const beforeField = await indices();
  await served.keyboard.press("ArrowRight");
  await served.waitForTimeout(400);
  assert.equal(await indices(), beforeField, "Arrow keys in a text field don't move the deck");
  await served.evaluate(() => document.getElementById("key-field").remove());
  results.push({ name: "deck-viewer-keys", keySteps });
  await served.click(".deck-expand");
  await served.evaluate(() => document.querySelector(".deck-frame").focus());
  const deckFrame = served.frames().find((frame) => frame !== served.mainFrame());
  await deckFrame.evaluate(() => { window.focus(); document.body.focus(); });
  await served.keyboard.press("Escape");
  const deckEsc = await served.evaluate(() => ({
    focused: document.activeElement === document.querySelector(".deck-frame"),
    pressed: document.querySelector(".deck-expand").getAttribute("aria-pressed"),
    overview: document.querySelector(".deck-frame").contentWindow.Reveal.isOverview()
  }));
  assert.deepEqual(deckEsc, { focused: true, pressed: "false", overview: false }, "Esc in the deck collapses the viewer and doesn't open the overview");
  results.push({ name: "deck-viewer-esc-in-deck", ...deckEsc });
  await servedContext.close();
  const html = await readFile(join(site, "index.html"), "utf8");
  assert.match(html, /slides\/attention\/index\.html/, "The site must link to the deck's viewer page");
  assert.doesNotMatch(html, /href="[^"]*slides\/attention\/slides\.html"/, "Site links open the viewer page, not the bare deck");
  assert.match(html, />Presentation slides</, "The overview must say the link opens slides");
  assert.match(html, /Slides: Attention in sequence models/, "The sidebar must label the deck as slides");
  await writeFile(join(output, "slide-checks.json"), JSON.stringify(results, null, 2));
  console.log("Slide checks passed: offline fonts/math, section headline and alignment, controls placement, dim builds, opt-outs, SCSS/scripts/plugins, chrome containment at four aspect ratios, phone scroll view, and custom backgrounds with nested sections, vertical stacks, and deck CSS classes; the deck's viewer page in the site with expand, Esc, page keys, outline and pop-out.");
} finally {
  await browser.close();
}
