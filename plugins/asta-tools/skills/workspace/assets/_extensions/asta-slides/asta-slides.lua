function Meta(meta)
  local options = meta["asta-slides"] or {}
  local flags = {}
  for _, name in ipairs({"theme", "section-header", "slide-number", "controls", "dim-previous"}) do
    flags["asta-slides-" .. name] = tostring(options[name] ~= false)
  end
  quarto.doc.add_html_dependency({
    name = "asta-slides",
    version = "0.1.0",
    scripts = {"asta-slides.js"},
    stylesheets = {"fonts.css", "chrome.css"},
    resources = {"fonts/Manrope.woff2", "fonts/RobotoMono.woff2"},
    meta = flags
  })
  return meta
end
