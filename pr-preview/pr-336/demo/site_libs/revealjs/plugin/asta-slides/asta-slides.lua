local function option_table(meta)
  local options = meta["asta-slides"] or {}
  if type(options) ~= "table" then options = {} end
  return options
end

function Meta(meta)
  local options = option_table(meta)
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
    stylesheets = {"fonts.css", "chrome.css"},
    resources = {"fonts/Manrope.woff2", "fonts/RobotoMono.woff2"},
    meta = flags
  })
  return meta
end

-- Tag every slide with its `#` section at build time, so the rendered HTML,
-- slide numbers and What changed all see the slides the audience sees.
-- `section-slides: false` drops the level-1 divider slides, as Beamer's \section.
function Pandoc(doc)
  local options = option_table(doc.meta)
  local dividers = options["section-slides"] ~= false
    and pandoc.utils.stringify(options["section-slides"] or "") ~= "false"
  local blocks, index, name = pandoc.List(), 0, nil
  local function tag(header)
    header.attributes["data-asta-section"] = tostring(index)
    header.attributes["data-asta-section-name"] = name
  end
  for _, block in ipairs(doc.blocks) do
    if block.t == "Header" and block.level == 1 then
      index, name = index + 1, pandoc.utils.stringify(block.content)
      if dividers then
        tag(block)
        blocks:insert(block)
      end
    else
      if block.t == "Header" and block.level == 2 and name then tag(block) end
      blocks:insert(block)
    end
  end
  doc.blocks = blocks
  return doc
end
