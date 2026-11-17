-- asta-templates provenance: under each figure whose folder carries a figure.json, a small line of
-- what it was made from: "Made from make_figure.py · 3 inputs · audit PASS", each linking its
-- file (relative to the rendered page, so it opens in the app's Files tab, or on GitHub once a
-- deployed site's links point there); "3 inputs" opens to list them. A figure made of
-- sub-figures gets one line, an entry per sub-figure that has a figure.json: "(a) …; (b) …".
-- A figure without one gets nothing. figure.json and where it is looked for: asta-templates.lua,
-- figure_provenance. The filter runs before Quarto turns the page's `::: {#fig-…}` blocks into
-- figures (`at: pre-ast`), and puts the line after the block, so it shows under the figure and
-- its caption.

local function load_lib()
  local env = setmetatable({}, { __index = _ENV })
  local chunk = assert(loadfile(quarto.utils.resolve_path("asta-templates.lua"), "t", env))
  chunk()
  return env.ASTA_TEMPLATES_LIB
end

local L

local function link(item, label)
  if item.missing then return L.html_escape(label or item.name) .. ' <span class="asta-made-missing">(missing)</span>' end
  if item.outside then
    return '<span title="' .. L.attr_escape(item.rel) .. '">' .. L.html_escape(label or item.name) ..
      '</span> <span class="asta-made-missing">(outside the workspace)</span>'
  end
  return '<a href="' .. L.attr_escape(item.href) .. '">' .. L.html_escape(label or item.name) .. "</a>"
end

local function entry(p)
  local parts = {}
  if p.script then parts[#parts + 1] = link(p.script) end
  local n = #p.inputs
  if n > 0 then
    local items = {}
    for _, it in ipairs(p.inputs) do
      local dir = pandoc.path.directory(it.rel)
      items[#items + 1] = "<li>" .. link(it) .. (dir ~= "." and (' <span class="asta-made-dir">' .. L.html_escape(dir) .. "</span>") or "") .. "</li>"
    end
    parts[#parts + 1] = '<details class="asta-made-inputs"><summary>' .. n .. (n == 1 and " input" or " inputs") ..
      "</summary><ul>" .. table.concat(items) .. "</ul></details>"
  end
  if p.audit then parts[#parts + 1] = link(p.audit, "audit" .. (p.verdict and (" " .. p.verdict) or "")) end
  return table.concat(parts, " · ")
end

local function image_of(div, here)
  local src = nil
  div:walk({ Image = function(i) src = src or i.src end })
  if not src or src:match("^%a[%w+.-]*:") or src:match("^/") then return nil end
  return L.normalize(here .. "/" .. L.url_decode(src))
end

local function line(div, here)
  local own = L.figure_provenance(div.identifier, image_of(div, here))
  local entries = {}
  if own then
    entries[1] = entry(own)
  else
    local k = 0
    for _, b in ipairs(div.content) do
      if b.t == "Div" and b.identifier:match("^fig%-") then
        k = k + 1
        local p = L.figure_provenance(b.identifier, image_of(b, here))
        if p then entries[#entries + 1] = "(" .. string.char(96 + k) .. ") " .. entry(p) end
      end
    end
  end
  if #entries == 0 then return nil end
  return pandoc.RawBlock("html", '<div class="asta-made-from">Made from ' .. table.concat(entries, "; ") .. "</div>")
end

local function walk(blocks, here)
  local out = pandoc.List()
  for _, b in ipairs(blocks) do
    out:insert(b)
    if b.t == "Div" then
      if b.identifier:match("^fig%-") then
        local l = line(b, here)
        if l then out:insert(l) end
      else
        b.content = walk(b.content, here)
      end
    end
  end
  return out
end

return {
  {
    Pandoc = function(doc)
      if not quarto.doc.is_format("html") then return nil end
      L = L or load_lib()
      local here = pandoc.path.directory(L.absolute(quarto.doc.input_file))
      local blocks = walk(doc.blocks, here)
      if #blocks == #doc.blocks then return nil end
      doc.blocks = blocks
      quarto.doc.add_html_dependency({ name = "asta-templates", version = "0.1.0", stylesheets = { "asta-templates.css" } })
      return doc
    end,
  },
}
