-- asta-pages: shortcodes that turn a run's files into page panels.
--
--   {{< asta-theories data="data/theorizer.json" >}}     the Theorizer panel
--   {{< asta-literature data="data/papers.json" >}}      the paper list (papers and searches only;
--                                                        data/theorizer.json also works)
--
--   {{< asta-theories data="data/theorizer.json,data/theorizer-v2.json" >}}
--                                                        several Theorizer projects on one page;
--                                                        theories in both files (same id and
--                                                        name) are shown once
--
-- The theories page groups theories by the query they were generated for (each theory's
-- `query` in the data file): one query is shown above the table, several get a tab each,
-- labelled "Query 1", "Query 2" ... or by `names="Original|Revised"` in that order. A paper
-- title links to its entry on the site's papers page, `papers="papers.html"` (relative to this
-- page; literature.html when not given).
--
-- `data` is relative to the page's own directory. The file is read at render time and
-- embedded in the page as JSON, so the rendered page needs no request at view time; the panel
-- is drawn by theories.js / literature.js. A missing or unreadable file renders a visible
-- error box in place of the panel and a warning in the render log, never a silent blank.


local function page_dir()
  local input = quarto.doc.input_file
  return pandoc.path.directory(input)
end

local function read_data(kwargs)
  local rel = pandoc.utils.stringify(kwargs["data"] or "")
  if rel == "" then
    return nil, "the shortcode names no data file; use data=\"data/theorizer.json\".", rel
  end
  local path = pandoc.path.join({ page_dir(), rel })
  local f = io.open(path, "r")
  if f == nil then
    quarto.log.warning("asta-pages: cannot read " .. path)
    return nil, "cannot read the data file " .. rel ..
      ". Write it with the workflow's data script, then render again.", rel
  end
  local text = f:read("a")
  f:close()
  return text, nil, rel
end

-- The stylesheet every panel shares. Added before any widget script.
local function css_dep()
  quarto.doc.add_html_dependency({ name = "asta-pages", version = "0.1.0", stylesheets = { "asta-pages.css" } })
end

local function add_deps(script)
  css_dep()
  quarto.doc.add_html_dependency({
    name = "asta-pages-" .. script,
    version = "0.1.0",
    scripts = { script .. ".js" },
  })
end

local function html_escape(s)
  return (s:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"))
end

local function panel(kind, script, kwargs)
  if not quarto.doc.is_format("html") then
    return pandoc.Null()
  end
  add_deps(script)
  local text, err, rel = read_data(kwargs)
  if err then
    quarto.log.warning("asta-" .. kind .. ": " .. err)
    return pandoc.RawBlock("html",
      '<div class="asta-panel"><div class="ap-error">This page has no data yet: ' ..
      html_escape(err) .. '</div></div>')
  end
  -- "</" cannot appear raw inside a <script> element; "<\/" is the same string in JSON.
  local safe = text:gsub("</", "<\\/")
  local id = "asta-" .. kind .. "-data"
  return pandoc.RawBlock("html",
    '<div class="asta-panel asta-' .. kind .. '" data-asta-source="' .. html_escape(rel) .. '"></div>\n' ..
    '<script type="application/json" id="' .. id .. '">' .. safe .. '</script>')
end

local function attr_escape(s)
  return (s:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"):gsub('"', "&quot;"))
end

-- A comma-separated list ("a.json, b.json"), trimmed, empty items dropped.
local function split_list(s, sep)
  local out = {}
  for item in (s .. sep):gmatch("(.-)" .. sep) do
    item = item:match("^%s*(.-)%s*$")
    if item ~= "" then out[#out + 1] = item end
  end
  return out
end

-- asta-theories: one or more data files (data="a.json,b.json"), one per Theorizer project,
-- each embedded as its own script element. A file that cannot be read gets an error box above
-- the panel; the panel still shows the files that could. `names="First|Second"` labels the
-- query tabs, in the order the queries first appear.
-- The page shows a finding only where a theory cites it (its Evidence tab); a run's other
-- findings can be most of its data file (28 MB of 30 for one run), and two such files in one page
-- were more than Quarto could write. Embed the cited ones only; the data file keeps them all.
-- Likewise the papers: only those a theory, a statement or a kept finding names are embedded
-- (several projects of one run each carry the run's whole paper list, the list page's job).
local function cited_findings_only(text)
  if not (pandoc.json and pandoc.json.decode) then return text end
  local ok, data = pcall(pandoc.json.decode, text, false)
  if not ok or type(data) ~= "table" or type(data.findings) ~= "table" or type(data.theories) ~= "table" then
    return text
  end
  local cited = {}
  for _, t in ipairs(data.theories) do
    if type(t) == "table" and type(t.evidence_results) == "table" then
      for _, r in ipairs(t.evidence_results) do cited[r] = true end
    end
  end
  local dropped = 0
  for sid, tb in pairs(data.findings) do
    if type(tb) == "table" and type(tb.rows) == "table" then
      local keep = {}
      for _, row in ipairs(tb.rows) do
        if type(row) == "table" and cited[row.result] then keep[#keep + 1] = row else dropped = dropped + 1 end
      end
      -- A table no theory cites is left out (an empty Lua table would be written as {}, not []).
      if #keep > 0 then tb.rows = keep else data.findings[sid] = nil end
    end
  end
  if type(data.papers) == "table" and #data.theories > 0 then
    local named = {}
    local function name(k) if k ~= nil then named[k] = true end end
    for _, t in ipairs(data.theories) do
      if type(t) == "table" then
        if type(t.papers) == "table" then for _, k in ipairs(t.papers) do name(k) end end
        for _, st in ipairs(type(t.statements) == "table" and t.statements or {}) do
          for _, f in ipairs({ "evidence", "conflicting", "unaccounted" }) do
            for _, ev in ipairs(type(st) == "table" and type(st[f]) == "table" and st[f] or {}) do
              if type(ev) == "table" then name(ev.paper) end
            end
          end
        end
      end
    end
    for _, tb in pairs(data.findings) do
      for _, row in ipairs(type(tb) == "table" and type(tb.rows) == "table" and tb.rows or {}) do
        if type(row) == "table" then name(row.paper) end
      end
    end
    local keep = {}
    for _, p in ipairs(data.papers) do
      local wanted = type(p) == "table" and named[p.key]
      for _, c in ipairs(type(p) == "table" and type(p.duplicates) == "table" and p.duplicates or {}) do
        if type(c) == "table" and named[c.key] then wanted = true end
      end
      if wanted then keep[#keep + 1] = p else dropped = dropped + 1 end
    end
    if #keep < #data.papers then data.papers = keep end
  end
  if dropped == 0 then return text end
  local encoded_ok, out = pcall(pandoc.json.encode, data)
  return encoded_ok and out or text
end

local function theories_panel(kwargs)
  if not quarto.doc.is_format("html") then
    return pandoc.Null()
  end
  add_deps("theories")
  local rels = split_list(pandoc.utils.stringify(kwargs["data"] or ""), ",")
  if #rels == 0 then
    local err = "the shortcode names no data file; use data=\"data/theorizer.json\"."
    quarto.log.warning("asta-theories: " .. err)
    return pandoc.RawBlock("html",
      '<div class="asta-panel"><div class="ap-error">This page has no data yet: ' .. html_escape(err) .. '</div></div>')
  end
  local errors, scripts, read = {}, {}, {}
  for _, rel in ipairs(rels) do
    local text, err = read_data({ data = rel })
    if err then
      quarto.log.warning("asta-theories: " .. err)
      errors[#errors + 1] = '<div class="asta-panel"><div class="ap-error">This page has no data yet: ' ..
        html_escape(err) .. '</div></div>'
    else
      read[#read + 1] = rel
      -- "</" cannot appear raw inside a <script> element; "<\/" is the same string in JSON.
      local safe = cited_findings_only(text):gsub("</", "<\\/")
      scripts[#scripts + 1] = '<script type="application/json" class="asta-theories-data"' ..
        (#scripts == 0 and ' id="asta-theories-data"' or '') ..
        ' data-asta-source="' .. attr_escape(rel) .. '">' .. safe .. '</script>'
    end
  end
  if #read == 0 then
    return pandoc.RawBlock("html", table.concat(errors, "\n"))
  end
  local names = split_list(pandoc.utils.stringify(kwargs["names"] or ""), "|")
  local names_attr = #names > 0 and (' data-asta-names="' .. attr_escape(quarto.json.encode(names)) .. '"') or ""
  -- papers="papers.html": the site's papers page (relative to this page), where a paper's title
  -- links (#paper-<corpus id or key>). theories.js uses literature.html when it is not given.
  local papers = pandoc.utils.stringify(kwargs["papers"] or "")
  local papers_attr = papers ~= "" and (' data-asta-papers="' .. attr_escape(papers) .. '"') or ""
  return pandoc.RawBlock("html", table.concat(errors, "\n") .. (#errors > 0 and "\n" or "") ..
    '<div class="asta-panel asta-theories" data-asta-source="' .. attr_escape(table.concat(read, ",")) .. '"' ..
    names_attr .. papers_attr .. '></div>\n' .. table.concat(scripts, "\n"))
end

return {
  ["asta-theories"] = function(args, kwargs, meta)
    return theories_panel(kwargs)
  end,
  ["asta-literature"] = function(args, kwargs, meta)
    return panel("literature", "literature", kwargs)
  end,
}
