(() => {
  "use strict";
  function start() {
    const deck = window.Reveal;
    if (!deck) return;
    const enabled = (name) => document.querySelector(`meta[name="asta-slides-${name}"]`)?.content !== "false";
    function install() {
      const slides = deck.getSlidesElement();
      if (slides.querySelector(":scope > .asta-slides-chrome")) return;
      const chrome = document.createElement("div");
      chrome.className = "asta-slides-chrome";
      slides.append(chrome);
      if (enabled("dim-previous")) document.body.classList.add("asta-slides-dim-enabled");
      for (const [option, selector] of [["controls", ".controls"], ["slide-number", ".slide-number"]]) {
        const node = deck.getRevealElement().querySelector(selector);
        if (node && enabled(option)) chrome.append(node);
        else if (node) node.remove();
      }
      const all = deck.getSlides();
      let currentSection = "";
      const sections = new Map(all.map((slide) => {
        const heading = slide.querySelector("h1:not(.title)");
        if (heading) currentSection = heading.textContent.trim();
        return [slide, currentSection];
      }));
      if (enabled("section-header") && [...sections.values()].some(Boolean)) {
        const label = document.createElement("div");
        label.className = "asta-slides-section";
        chrome.append(label);
        document.body.classList.add("asta-slides-with-section");
        const update = () => {
          label.textContent = sections.get(deck.getCurrentSlide()) || "";
          label.hidden = !label.textContent;
        };
        deck.on("slidechanged", update);
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
