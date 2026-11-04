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
      present: document.querySelector(".deck-present").getAttribute("href"),
      src: document.querySelector(".deck-frame").getAttribute("src"),
      sidebar: Boolean(sidebar && sidebar.getBoundingClientRect().width > 0 && getComputedStyle(sidebar).display !== "none"),
      ratio: frame.width / frame.height, top: frame.top, bottom: frame.bottom, left: frame.left, right: frame.right,
      viewport: [innerWidth, innerHeight]
    };
  });
  assert.equal(inSite.title, "Attention in sequence models", "The viewer bar names the deck");
  assert.match(inSite.where, /Written in slides\/attention\/slides\.qmd/, "The viewer bar says where the deck is written");
  assert.equal(inSite.present, "slides.html", "Present opens the deck alone");
  assert.equal(inSite.src, "slides.html", "The viewer plays the deck in place");
  assert.ok(inSite.sidebar, "The viewer page shows the site's sidebar");
  assert.ok(Math.abs(inSite.ratio - 16 / 9) < 0.01, `The deck plays at 16:9 (got ${inSite.ratio})`);
  assert.ok(inSite.top >= 0 && inSite.bottom <= inSite.viewport[1] + 0.5 && inSite.right <= inSite.viewport[0] + 0.5, "A whole slide is in view");
  await viewer.waitForFunction(() => document.querySelector(".deck-frame").contentDocument === null
    || document.querySelector(".deck-frame").contentDocument.querySelector(".reveal .slides section"));
  await viewer.screenshot({ path: join(output, "deck-viewer.png") });
  results.push({ name: "deck-viewer", ...inSite });
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
  await viewerContext.close();
  const html = await readFile(join(site, "index.html"), "utf8");
  assert.match(html, /slides\/attention\/index\.html/, "The site must link to the deck's viewer page");
  assert.doesNotMatch(html, /href="[^"]*slides\/attention\/slides\.html"/, "Site links open the viewer page, not the bare deck");
  assert.match(html, />Presentation slides</, "The overview must say the link opens slides");
  assert.match(html, /Slides: Attention in sequence models/, "The sidebar must label the deck as slides");
  await writeFile(join(output, "slide-checks.json"), JSON.stringify(results, null, 2));
  console.log("Slide checks passed: offline fonts/math, section headline and alignment, controls placement, dim builds, opt-outs, SCSS/scripts/plugins, chrome containment at four aspect ratios, phone scroll view, and custom backgrounds with nested sections, vertical stacks, and deck CSS classes; the deck's viewer page in the site with expand and Esc.");
} finally {
  await browser.close();
}
