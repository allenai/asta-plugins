// Run against an actual Quarto render, not a mock document.
// npm test -- <rendered site directory> <output directory> [reference URL]
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { chromium } from "playwright";

const site = resolve(process.argv[2] ?? "../../examples/workspace/_site");
const output = resolve(process.argv[3] ?? "artifacts");
const referenceURL = process.argv[4];
// Generate a real diff from the rendered example, including its evidence CSS.
// The extra light sheet reproduces Quarto versions that emit helper sheets.
const fixture = await mkdtemp(join(tmpdir(), "workspace-diff-theme-"));
try {
  await mkdir(join(fixture, "old"));
  await mkdir(join(fixture, "new/lit-review"), { recursive: true });
  const index = await readFile(join(site, "index.html"), "utf8");
  const primary = index.match(/<link\b(?=[^>]*id="quarto-bootstrap")(?=[^>]*data-mode="light")[^>]*>/)[0];
  const extra = primary.replace('class="quarto-color-scheme"', 'class="quarto-color-scheme-extra"');
  await writeFile(join(fixture, "new/index.html"), index.replace("</head>", extra + "</head>"));
  await writeFile(join(fixture, "new/lit-review/index.html"), await readFile(join(site, "lit-review/index.html")));
  const generated = spawnSync("python3", [
    "../../plugins/asta-tools/skills/workspace/assets/what-changed.py",
    "--old", join(fixture, "old"), "--new", join(fixture, "new"),
    "--out", join(site, "what-changed-theme-check.html"),
  ], { encoding: "utf8" });
  assert.equal(generated.status, 0, generated.stderr);
} finally {
  await rm(fixture, { recursive: true, force: true });
}
await mkdir(output, { recursive: true });
// Bind port 0 in the serving process so selecting a port cannot race another
// process. Announce it only after HTTPServer has successfully bound the socket.
const server = spawn("python3", ["-u", "-c", `
import functools, http.server, sys
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=sys.argv[1])
with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
    print(server.server_port, flush=True)
    server.serve_forever()
`, site], { stdio: ["ignore", "pipe", "inherit"] });
let browser;
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

async function assertBundledFonts(page) {
  const loaded = await page.evaluate(async () => {
    const families = ["Manrope", "Roboto Mono"];
    return Promise.all(families.map(async (family) => {
      const faces = await document.fonts.load(`16px "${family}"`);
      return { family, count: faces.length, loaded: faces.every((face) => face.status === "loaded") };
    }));
  });
  for (const face of loaded) {
    assert.ok(face.count > 0 && face.loaded, `${face.family} must load from the rendered site, without fallback`);
  }
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
  await assertBundledFonts(page);
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
  const port = await new Promise((resolve, reject) => {
    const lines = createInterface({ input: server.stdout });
    const fail = (error) => { cleanup(); reject(error); };
    const exited = (code, signal) => fail(new Error(`Site server exited before binding (${signal ?? code})`));
    const timer = setTimeout(() => fail(new Error("Site server did not announce a port")), 5000);
    function cleanup() {
      clearTimeout(timer);
      lines.close();
      server.off("error", fail);
      server.off("exit", exited);
    }
    server.once("error", fail);
    server.once("exit", exited);
    lines.once("line", (line) => {
      const value = Number(line);
      if (!Number.isInteger(value) || value < 1 || value > 65535) {
        fail(new Error(`Invalid site server port: ${line}`));
        return;
      }
      cleanup();
      resolve(value);
    });
  });
  const base = `http://127.0.0.1:${port}`;
  browser = await chromium.launch({ headless: true });
  for (const mode of ["light", "dark"]) {
    const context = await browser.newContext({ viewport: { width: 1100, height: 900 }, colorScheme: mode, deviceScaleFactor: 1 });
    const fontResponses = [];
    context.on("response", (response) => {
      if (response.request().resourceType() === "font") fontResponses.push(response);
    });
    const page = await context.newPage();
    await page.goto(`${base}/appearance.html`, { waitUntil: "networkidle" });
    // A fresh visit starts dark even when the operating system prefers light.
    await assertMode(page, "dark");
    await page.emulateMedia({ colorScheme: mode === "light" ? "dark" : "light" });
    await assertMode(page, "dark");
    if (mode === "light") await page.locator(".quarto-color-scheme-toggle:visible").first().click();
    results.modes[mode] = await assertMode(page, mode);
    for (const name of ["Manrope.woff2", "RobotoMono.woff2"]) {
      assert.ok(fontResponses.some((response) => {
        const url = new URL(response.url());
        return url.origin === base && url.pathname.endsWith(`/fonts/${name}`) && response.status() === 200;
      }), `${name} must be served successfully by the site`);
    }
    assert.ok(fontResponses.every((response) => new URL(response.url()).origin === base), "Fonts must not contact another host");
    const link = page.locator("main a:not(.anchorjs-link)").first();
    const linkColor = await link.evaluate((el) => getComputedStyle(el).color);
    await link.hover();
    assert.notEqual(await link.evaluate((el) => getComputedStyle(el).color), linkColor, "Links must show hover feedback");
    await page.mouse.move(0, 0);
    const primaryText = await page.evaluate(() => {
      const text = document.createElement("span");
      text.className = "text-primary";
      document.querySelector("main").append(text);
      const color = getComputedStyle(text).color;
      text.remove();
      return color;
    });
    assert.ok(contrast(rgba(primaryText), rgba(results.modes[mode].background)) >= 4.5, "Primary text must be readable");
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
  results.diffModes = [];
  for (const scenario of [
    { system: "light", stored: null, mode: "dark" },
    { system: "dark", stored: null, mode: "dark" },
    { system: "dark", stored: "default", mode: "light" },
    { system: "light", stored: "alternate", mode: "dark" },
  ]) {
    const context = await browser.newContext({ colorScheme: scenario.system });
    if (scenario.stored) await context.addInitScript((stored) => {
      localStorage.setItem("quarto-color-scheme", stored);
    }, scenario.stored);
    const page = await context.newPage();
    await page.goto(`${base}/what-changed-theme-check.html`, { waitUntil: "networkidle" });
    await settled(page);
    await assertBundledFonts(page);
    const actual = await page.evaluate(() => {
      const css = (el) => getComputedStyle(el);
      const body = css(document.body);
      const insertion = css(document.querySelector(".legend ins"));
      const evidence = css(document.querySelector(".ev"));
      return {
        mode: document.documentElement.dataset.wcMode,
        bodyMode: document.body.className,
        background: body.backgroundColor, text: body.color, font: body.fontFamily,
        insertedBackground: insertion.backgroundColor, insertedText: insertion.color,
        evidenceBorder: evidence.borderBottomColor,
        sheets: [...document.querySelectorAll("link.quarto-color-scheme, link.quarto-color-scheme-extra")]
          .map((link) => ({ extra: link.classList.contains("quarto-color-scheme-extra"),
            alternate: link.classList.contains("quarto-color-alternate"), rel: link.rel })),
      };
    });
    assert.equal(actual.mode, scenario.mode);
    assert.equal(actual.bodyMode, `quarto-${scenario.mode}`);
    assert.equal(actual.background, scenario.mode === "dark" ? "rgb(3, 38, 41)" : "rgb(250, 242, 233)");
    assert.equal(actual.text, scenario.mode === "dark" ? "rgb(250, 242, 233)" : "rgb(10, 50, 53)");
    assert.match(actual.font, /Manrope/);
    assert.equal(actual.insertedBackground, scenario.mode === "dark" ? "rgb(18, 52, 31)" : "rgb(215, 245, 221)");
    assert.ok(contrast(rgba(actual.insertedText), rgba(actual.insertedBackground)) >= 4.5, "Diff insertions must be readable");
    assert.ok(contrast(rgba(actual.evidenceBorder), rgba(actual.background)) >= 3, "Diff evidence underline must be visible");
    assert.equal(actual.evidenceBorder, scenario.mode === "dark" ? "rgb(15, 203, 140)" : "rgb(16, 82, 87)");
    assert.ok(actual.sheets.some((sheet) => sheet.extra), "Exercise the extra stylesheet case");
    for (const sheet of actual.sheets) {
      const enabled = !sheet.extra && (!sheet.alternate || scenario.mode === "dark");
      assert.equal(sheet.rel, enabled ? "stylesheet" : "disabled-stylesheet");
    }
    results.diffModes.push({ ...scenario, ...actual });
    await context.close();
  }
  await writeFile(`${output}/checks.json`, JSON.stringify(results, null, 2));
  console.log("Theme checks passed: dark default regardless of system preference, persistent toggle, evidence contrast, identical layout, visible headings, and matching What changed palettes in both modes.");
} finally {
  await browser?.close();
  server.kill();
  await rm(join(site, "what-changed-theme-check.html"), { force: true });
}
