window.AstaSlides = {
  id: "asta-slides",
  init(deck) {
    "use strict";
    // Capture inherited backgrounds before Reveal moves vertical slides into
    // scroll pages and removes their stacks. The marker survives view changes.
    const customBackground = ["background", "background-color", "background-image", "background-gradient", "background-video", "background-iframe"]
      .map((attribute) => `[data-${attribute}]`).join(",");
    for (const stack of deck.getSlidesElement().querySelectorAll(":scope > section")) {
      if (stack.matches(customBackground)) {
        for (const slide of stack.querySelectorAll(":scope > section")) slide.classList.add("asta-slides-inherited-background");
      }
    }
    const option = (name) => document.querySelector(`meta[name="asta-slides-${name}"]`)?.content;
    const enabled = (name) => option(name) !== "false";
    function install() {
      const slides = deck.getSlidesElement();
      if (slides.querySelector(":scope > .asta-slides-chrome")) return;
      const chrome = document.createElement("div");
      chrome.className = "asta-slides-chrome";
      slides.append(chrome);
      if (enabled("dim-previous")) document.body.classList.add("asta-slides-dim-enabled");
      for (const [name, selector] of [["controls", ".controls"], ["slide-number", ".slide-number"]]) {
        const node = deck.getRevealElement().querySelector(selector);
        if (node) {
          // Quarto still updates these nodes on slide changes, even when hidden.
          chrome.append(node);
          if (!enabled(name)) node.hidden = true;
        }
      }
      // Quarto's `controls: auto` shows the arrows only when embedded or with vertical slides.
      const controls = chrome.querySelector(":scope > .controls");
      const placeNumber = () => chrome.classList.toggle("asta-slides-controls-shown",
        !!controls && !controls.hidden && getComputedStyle(controls).display !== "none");
      deck.on("resize", placeNumber);
      placeNumber();

      // The Lua filter tags each slide with its `#` section at build time.
      const names = [];
      const sections = new Map(deck.getSlides().map((slide) => {
        const index = Number(slide.dataset.astaSection) - 1;
        if (index >= 0) names[index] ??= slide.dataset.astaSectionName ?? "";
        return [slide, index >= 0 ? index : -1];
      }));
      const mode = option("section-header") === "current" ? "current" : "all";
      if (names.length) document.body.classList.add("asta-slides-with-section");
      if (enabled("section-header") && names.length) {
        const line = document.createElement("div");
        line.className = `asta-slides-section asta-slides-section-${mode}`;
        const items = mode === "all" ? names.map((name) => {
          const item = document.createElement("span");
          item.textContent = name;
          line.append(item);
          return item;
        }) : [];
        chrome.append(line);
        // Line up with the slide titles wherever the theme puts them, in slide units.
        const align = () => {
          const slide = deck.getCurrentSlide();
          const title = slide?.querySelector(":scope > h2");
          if (!title || slide.classList.contains("center")) return;
          const left = (title.getBoundingClientRect().left - slides.getBoundingClientRect().left) / deck.getScale();
          chrome.style.setProperty("--asta-slides-title-left", `${Math.round(left)}px`);
        };
        // Until a titled slide is shown, estimate from the first one's styles (valid while it is hidden).
        const first = deck.getSlides().find((slide) => slide.querySelector(":scope > h2") && !slide.classList.contains("center"));
        if (first) {
          const px = (node, property) => parseFloat(getComputedStyle(node)[property]) || 0;
          const h2 = first.querySelector(":scope > h2");
          chrome.style.setProperty("--asta-slides-title-left", `${Math.round(px(first, "paddingLeft") + px(h2, "marginLeft"))}px`);
        }
        const update = () => {
          const slide = deck.getCurrentSlide();
          const current = sections.get(slide) ?? -1;
          if (mode === "current") line.textContent = names[current] ?? "";
          items.forEach((item, index) => item.classList.toggle("current", index === current));
          // Hidden on any opening slide before the first section.
          line.hidden = current < 0;
          align();
        };
        deck.on("slidechanged", update);
        deck.on("slidetransitionend", align);
        deck.on("resize", align);
        update();
      }
      // Reveal owns navigation, fragment state, keyboard and touch handling.
      deck.layout();
    }
    // In a viewer page's frame: take navigation keys from the page and report the slide.
    if (window.parent !== window) {
      const codes = { ArrowLeft: 37, ArrowUp: 38, ArrowRight: 39, ArrowDown: 40, " ": 32,
        PageUp: 33, PageDown: 34, End: 35, Home: 36 };
      window.addEventListener("message", (event) => {
        const data = event.data;
        if (event.source !== window.parent || data?.astaSlides !== "key" || !(data.key in codes)) return;
        // Reveal's keyboard handler reads keyCode, which KeyboardEvent's constructor can't set.
        const key = new KeyboardEvent("keydown", { key: data.key, shiftKey: !!data.shiftKey, bubbles: true, cancelable: true });
        Object.defineProperty(key, "keyCode", { get: () => codes[data.key] });
        Object.defineProperty(key, "which", { get: () => codes[data.key] });
        document.dispatchEvent(key);
      });
      // Reveal may write the hash after its events, so report once it has.
      const report = () => setTimeout(() => window.parent.postMessage({ astaSlides: "location", hash: location.hash }, "*"));
      for (const name of ["ready", "slidechanged", "fragmentshown", "fragmenthidden"]) deck.on(name, report);
      if (deck.isReady()) report();
    }
    if (deck.isReady()) install();
    else deck.on("ready", install);
  }
};
