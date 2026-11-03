(() => {
  "use strict";
  function start() {
    const deck = window.Reveal;
    if (!deck) return;
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
        if (node && enabled(name)) chrome.append(node);
        else if (node) node.remove();
      }
      // Quarto's `controls: auto` shows the arrows only when embedded or with vertical slides.
      const controls = chrome.querySelector(":scope > .controls");
      const placeNumber = () => chrome.classList.toggle("asta-slides-controls-shown",
        !!controls && getComputedStyle(controls).display !== "none");
      deck.on("resize", placeNumber);
      placeNumber();

      const names = [];
      const sections = new Map(deck.getSlides().map((slide) => {
        const heading = slide.querySelector("h1:not(.title)");
        if (heading) names.push(heading.textContent.trim());
        return [slide, names.length - 1];
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
          line.hidden = mode === "current" ? !line.textContent : slide?.id === "title-slide";
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
    if (deck.isReady()) install();
    else deck.on("ready", install);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();
