function Meta(meta)
  local options = meta["asta-slides"] or {}
  if type(options) ~= "table" then options = {} end
  local flags = {}
  for _, name in ipairs({"section-header", "slide-number", "controls", "dim-previous"}) do
    local value = options[name]
    if type(value) ~= "boolean" and value ~= nil then value = pandoc.utils.stringify(value) end
    if value == nil or value == true then value = name == "section-header" and "all" or "true" end
    flags["asta-slides-" .. name] = tostring(value)
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
