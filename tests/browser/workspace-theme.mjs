// Run against an actual Quarto render, not a mock document.
// npm test -- <rendered site directory> <output directory> [reference URL]
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";

const site = resolve(process.argv[2] ?? "../../examples/workspace/_site");
const output = resolve(process.argv[3] ?? "artifacts");
const referenceURL = process.argv[4];
await mkdir(output, { recursive: true });
const server = spawn("python3", ["-m", "http.server", "4848", "--bind", "127.0.0.1", "--directory", site], { stdio: "ignore" });
const base = "http://127.0.0.1:4848";
const browser = await chromium.launch({ headless: true });
const results = { referenceURL, modes: {} };

function rgba(color, under = [0, 0, 0]) {
  const values = color.match(/[\d.]+/g).map(Number);
  const alpha = values[3] ?? 1;
  return values.slice(0, 3).map((value, i) => value * alpha + under[i] * (1 - alpha));
}

function contrast(a, b) {
  const luminance = (rgb) => rgb.map((v) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }).reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
  const [low, high] = [luminance(a), luminance(b)].sort((a, b) => a - b);
  return (high + 0.05) / (low + 0.05);
}

async function settled(page) {
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
  await page.waitForTimeout(200); // finish Quarto's theme and navbar updates
}

async function metrics(page) {
  return page.evaluate(() => {
    const elements = [...document.querySelectorAll("main h1, main h2, main h3, main p, main li, main pre")];
    return elements.map((el) => {
      const box = el.getBoundingClientRect();
      const css = getComputedStyle(el);
      return { x: box.x, y: box.y, width: box.width, height: box.height, font: css.fontFamily, size: css.fontSize, lineHeight: css.lineHeight };
    });
  });
}

async function assertMode(page, mode) {
  await page.waitForFunction((mode) => document.body.classList.contains(`quarto-${mode}`), mode);
  await settled(page);
  const colors = await page.evaluate(() => {
    const body = getComputedStyle(document.body);
    const link = document.querySelector("main a:not(.anchorjs-link)");
    return { background: body.backgroundColor, text: body.color, link: getComputedStyle(link).color, font: body.fontFamily };
  });
  assert.equal(colors.background, mode === "light" ? "rgb(250, 242, 233)" : "rgb(3, 38, 41)");
  assert.equal(colors.text, mode === "light" ? "rgb(10, 50, 53)" : "rgb(250, 242, 233)");
  assert.match(colors.font, /Manrope/);
  const background = rgba(colors.background);
  assert.ok(contrast(rgba(colors.link), background) >= 4.5, "Body links must remain readable");
  const code = await page.locator("main p code:not(.sourceCode)").first().evaluate((el) => {
    const style = getComputedStyle(el);
    return { color: style.color, background: style.backgroundColor };
  });
  const codeBackground = rgba(code.background, background);
  const codeContrast = contrast(rgba(code.color, codeBackground), codeBackground);
  assert.ok(codeContrast >= 4.5, `Inline code must remain readable (${codeContrast.toFixed(2)}:1)`);
  colors.inlineCodeContrast = codeContrast;
  return colors;
}

try {
  for (let attempt = 0; ; attempt++) {
    try {
      const response = await fetch(base);
      assert.equal(response.status, 200);
      break;
    } catch (error) {
      if (attempt >= 50) throw error;
      await new Promise((done) => setTimeout(done, 100));
    }
  }
  for (const mode of ["light", "dark"]) {
    const context = await browser.newContext({ viewport: { width: 1100, height: 900 }, colorScheme: mode, deviceScaleFactor: 1 });
    const page = await context.newPage();
    await page.goto(`${base}/appearance.html`, { waitUntil: "networkidle" });
    // A fresh visit starts dark even when the operating system prefers light.
    await assertMode(page, "dark");
    await page.emulateMedia({ colorScheme: mode === "light" ? "dark" : "light" });
    await assertMode(page, "dark");
    if (mode === "light") await page.locator(".quarto-color-scheme-toggle:visible").first().click();
    results.modes[mode] = await assertMode(page, mode);
    const before = await metrics(page);
    const toggle = page.locator(".quarto-color-scheme-toggle:visible").first();
    assert.equal(await toggle.count(), 1, "Quarto must expose a visible theme toggle");
    const other = mode === "light" ? "dark" : "light";
    await toggle.click();
    await assertMode(page, other);
    const after = await metrics(page);
    assert.equal(before.length, after.length);
    for (let i = 0; i < before.length; i++) {
      for (const field of ["x", "y", "width", "height"]) {
        assert.ok(Math.abs(before[i][field] - after[i][field]) < 0.6, `Mode switch moved element ${i} (${field})`);
      }
      for (const field of ["font", "size", "lineHeight"]) assert.equal(before[i][field], after[i][field]);
    }
    await page.reload({ waitUntil: "networkidle" });
    await assertMode(page, other); // explicit toggle persists across navigation
    await page.locator(".quarto-color-scheme-toggle:visible").first().click();
    await assertMode(page, mode);
    // Real evidence markup, with both pointer and keyboard access.
    await page.goto(`${base}/lit-review/index.html`, { waitUntil: "networkidle" });
    await page.waitForFunction((mode) => document.body.classList.contains(`quarto-${mode}`), mode);
    await settled(page);
    const evidence = page.locator(".ev").first();
    const evidenceColors = await evidence.evaluate((el) => {
      const css = getComputedStyle(el);
      return { border: css.borderBottomColor, background: getComputedStyle(document.body).backgroundColor };
    });
    assert.ok(contrast(rgba(evidenceColors.border), rgba(evidenceColors.background)) >= 3, "Evidence underline must be visible");
    for (const interaction of ["hover", "focus"]) {
      await page.mouse.move(0, 0);
      if (interaction === "hover") await evidence.hover();
      else await evidence.focus();
      await page.waitForTimeout(400);
      assert.ok(await evidence.locator(".ev-card").isVisible(), `Evidence quote must open on ${interaction}`);
      const ratios = await evidence.locator(".ev-card").evaluate((card) => {
        const bg = getComputedStyle(card).backgroundColor;
        return [...card.querySelectorAll(".ev-quote, .ev-pop-src, a, .ev-src-label, .ev-prov-body")]
          .map((el) => ({ color: getComputedStyle(el).color, background: bg }));
      });
      assert.ok(ratios.length >= 2, "Check the quote and citation");
      for (const colors of ratios) {
        const bg = rgba(colors.background, rgba(evidenceColors.background));
        assert.ok(contrast(rgba(colors.color, bg), bg) >= 4.5, `Evidence text must be readable in ${mode}`);
      }
    }
    await page.goto(`${base}/appearance.html`, { waitUntil: "networkidle" });
    await assertMode(page, mode);
    const workspace = await page.screenshot({ path: `${output}/workspace-${mode}.png` });

    // Scroll inside a real, rendered example section.
    await assertMode(page, mode);
    const section = page.locator("main section.level2").filter({ has: page.locator("h2") });
    let checked = false;
    for (let i = 0; i < await section.count(); i++) {
      const heading = section.nth(i).locator(":scope > h2");
      const bounds = await section.nth(i).boundingBox();
      if (!bounds || bounds.height < 350) continue;
      await page.evaluate((y) => window.scrollTo(0, y), bounds.y + await page.evaluate(() => window.scrollY) + 160);
      await page.waitForTimeout(300);
      const box = await heading.boundingBox();
      const offset = await heading.evaluate((el) => parseFloat(getComputedStyle(el).top));
      assert.ok(box.y >= offset - 1 && box.y <= offset + 1, "Current section heading must remain pinned");
      assert.ok(await heading.evaluate((el) => {
        const r = el.getBoundingClientRect();
        return el.contains(document.elementFromPoint(r.x + 15, r.y + r.height / 2));
      }), "Pinned heading must remain visible above page content");
      await page.evaluate(() => window.scrollBy(0, -40));
      await page.waitForTimeout(500); // reveal Quarto's navigation header
      const headerBottom = await page.locator("#quarto-header").evaluate((el) => el.getBoundingClientRect().bottom);
      const readingHeading = await heading.boundingBox();
      assert.ok(readingHeading.y >= headerBottom - 1, "Returning navigation must not cover the heading");
      await page.screenshot({ path: `${output}/workspace-${mode}-reading.png` });
      checked = true;
      break;
    }
    assert.ok(checked, "The example needs a long section to exercise heading tracking");

    if (referenceURL) {
      const reference = await context.newPage();
      await reference.goto(referenceURL, { waitUntil: "domcontentloaded", timeout: 60000 });
      await reference.locator("body").waitFor();
      await reference.evaluate(() => document.fonts.ready);
      await reference.waitForTimeout(7000); // allow the public app to mount
      const title = await reference.title();
      assert.match(title, /Asta/i, "Reference must be the actual Asta app");
      const referenceImage = await reference.screenshot({ path: `${output}/asta-reference-${mode}.png` });
      const comparison = await context.newPage();
      await comparison.setViewportSize({ width: 2200, height: 950 });
      await comparison.setContent(`<!doctype html><style>
        body { margin:0; background:#faf2e9; color:#0a3235; font:600 16px Manrope,Arial,sans-serif; }
        header { height:50px; display:flex; align-items:center; }
        header span { width:1100px; padding-left:20px; box-sizing:border-box; }
        main { display:flex; } img { display:block; width:1100px; height:900px; }
      </style><header><span>Workspace preview · ${mode}</span><span>asta.allen.ai · live app reference</span></header>
      <main><img src="data:image/png;base64,${workspace.toString("base64")}"><img src="data:image/png;base64,${referenceImage.toString("base64")}"></main>`);
      await comparison.locator("img").evaluateAll((images) => Promise.all(images.map((img) => img.decode())));
      await comparison.screenshot({ path: `${output}/workspace-${mode}-comparison.png` });
    }
    await context.close();
  }
  await writeFile(`${output}/checks.json`, JSON.stringify(results, null, 2));
  console.log("Theme checks passed: dark default regardless of system preference, persistent toggle, evidence contrast, identical layout, and visible headings in both modes.");
} finally {
  await browser.close();
  server.kill();
}
