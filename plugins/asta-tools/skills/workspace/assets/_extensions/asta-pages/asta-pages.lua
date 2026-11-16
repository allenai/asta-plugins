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
--
--   {{< asta-autods data="autods" >}}                    AutoDiscovery runs, drawn as the hosted
--                                                        run page (autodiscovery.allen.ai)
--
-- asta-autods's `data` is a run's own files: `asta autodiscovery results` JSON ({run,
-- experiments}: tree, figures, settings), the hosted Download → JSON or → CSV (the CSV has no
-- tree, code or figures), a local run's output folder (mcts_node_*.json, rich_outputs/), or a
-- run folder (run.md with experiments.csv and/or results.json). A folder of such files and
-- folders is several runs, one per file or folder, in name
-- order; a run whose results and CSV both sit there is drawn once, from the results. The page
-- carries the runs as JSON like the other panels (each figure in one form, the smallest; a
-- local node without its LLM transcript); autods.js draws it. `name` titles a single run.
--
--   {{< asta-workflow >}}                                 the run's workflow diagram
--
-- reads `workflow.mmd` beside the page (or file="..."), a Mermaid diagram the agent keeps
-- current, and renders it under a "Workflow" heading with the Mermaid runtime that Quarto
-- ships (copied into the site, so nothing loads from elsewhere). With no such file it renders
-- nothing, heading included, so a run page can carry the shortcode before a diagram exists.

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

local function read_file(path)
  local f = io.open(path, "r")
  if f == nil then return nil end
  local text = f:read("a")
  f:close()
  return text
end

local function list_dir(path)
  local ok, names = pcall(pandoc.system.list_directory, path)
  if not ok then return nil end
  table.sort(names)
  return names
end

-- JSON from a file's text, or nil. Python writes NaN and Infinity, which JSON has no words for:
-- read as null. Empty text is nil without asking the decoder (which logs what it cannot read).
local function decode_json(text)
  if type(text) ~= "string" or text:match("^%s*$") then return nil end
  local clean = text:gsub("([:,%[]%s*)%-?NaN(%s*[,%]}])", "%1null%2"):gsub("([:,%[]%s*)%-?Infinity(%s*[,%]}])", "%1null%2")
  local ok, data = pcall(quarto.json.decode, clean)
  if ok then return data end
  return nil
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

-- ---- asta-autods ---------------------------------------------------------------------------


local function is_node_file(name) return name:match("^mcts_node_%d+_%d+%.json$") ~= nil end

local function has_nodes(names)
  for _, n in ipairs(names or {}) do if is_node_file(n) then return true end end
  return false
end

-- The fields of an mcts_node record the run view shows. The rest (the LLM messages, the
-- untried and tried experiment lists) is most of the file and nothing a reader opens.
local NODE_FIELDS = { "id", "parent_id", "creation_idx", "created_at", "success", "surprising",
  "normalized_surprisal", "belief_change", "prior", "posterior", "hypothesis", "experiment_plan",
  "code", "code_output", "analysis", "review", "time_elapsed" }
-- A figure is kept in one form, the smallest of its images (the hosted RichOutputsSection shows
-- SVG, then PNG, then JPEG; they are the same figure). A run's every figure in every form is
-- 10-20 MB a run; one form is a third of that.
local IMAGE_MIMES = { "image/svg+xml", "image/png", "image/jpeg" }

local function slim_bundles(bundles)
  if type(bundles) ~= "table" then return nil end
  local out = {}
  for _, b in ipairs(bundles) do
    if type(b) == "table" then
      local best
      for _, mime in ipairs(IMAGE_MIMES) do
        if type(b[mime]) == "string" and (best == nil or #b[mime] < #b[best]) then best = mime end
      end
      if best then out[#out + 1] = { [best] = b[best] }
      elseif type(b["text/plain"]) == "string" then out[#out + 1] = { ["text/plain"] = b["text/plain"] } end
    end
  end
  return out
end

-- A local run's settings and what it was told, for its Session configuration: AutoDiscovery
-- writes the run's arguments to args.json in the output folder (`user_query` is the intent), and
-- `dataset_metadata` names the file holding the run's name, description and datasets (a path
-- from where the run was started, or absolute).
local ARG_FIELDS = { "n_experiments", "exploration_weight", "mcts_selection", "surprisal_width", "evidence_weight" }

local function local_meta(dir)
  local args = decode_json(read_file(pandoc.path.join({ dir, "args.json" })))
  if type(args) ~= "table" then return nil end
  local meta = { intent = args.user_query }
  for _, k in ipairs(ARG_FIELDS) do meta[k] = args[k] end
  local mp = args.dataset_metadata
  if type(mp) == "string" and mp ~= "" then
    local paths = { mp }
    if not pandoc.path.is_absolute(mp) then
      paths = { pandoc.path.join({ quarto.project.directory or ".", mp }), pandoc.path.join({ dir, mp }) }
    end
    for _, p in ipairs(paths) do
      local m = decode_json(read_file(p))
      if type(m) == "table" then
        meta.name, meta.description, meta.datasets = m.name, m.description, m.datasets
        meta.intent = meta.intent or m.intent
        break
      end
    end
  end
  return meta
end

local function node_run(dir, rel)
  local nodes, skipped = {}, 0
  for _, name in ipairs(list_dir(dir) or {}) do
    -- mcts_node_1_0 loads the dataset; it is never an experiment (the hosted API drops it too).
    if is_node_file(name) and name ~= "mcts_node_1_0.json" then
      local node = decode_json(read_file(pandoc.path.join({ dir, name })))
      if type(node) == "table" then
        local slim = {}
        for _, k in ipairs(NODE_FIELDS) do slim[k] = node[k] end
        local suffix = tostring(node.id or name):match("(%d+_%d+)")
        local ro = suffix and read_file(pandoc.path.join({ dir, "rich_outputs", "ro_" .. suffix .. ".json" }))
        local figures = slim_bundles(decode_json(ro))
        if figures and #figures > 0 then slim.figures = figures end
        nodes[#nodes + 1] = slim
      else
        skipped = skipped + 1
      end
    end
  end
  if skipped > 0 then
    quarto.log.warning("asta-autods: " .. skipped .. " node file(s) in " .. rel .. " could not be read")
  end
  return { kind = "nodes", source = rel, nodes = nodes, skipped = skipped, meta = local_meta(dir) }
end

local function file_run(path, rel)
  local text = read_file(path)
  if text == nil then return nil end
  if not rel:lower():match("%.json$") then
    return { kind = "csv", source = rel, text = text }
  end
  -- Results JSON (`asta autodiscovery results`, the hosted Download → JSON): each experiment's
  -- figures kept in one form. A file that does not parse is passed as text, for the page to
  -- say so.
  local ok, data = pcall(quarto.json.decode, text)
  if not ok or type(data) ~= "table" then
    return { kind = "json", source = rel, text = text }
  end
  local list = data.experiments or data
  if type(list) == "table" then
    for _, e in ipairs(list) do
      if type(e) == "table" then
        if type(e.rich_outputs) == "table" then e.rich_outputs = slim_bundles(e.rich_outputs) end
        if type(e.richOutputs) == "table" then e.richOutputs = slim_bundles(e.richOutputs) end
      end
    end
  end
  return { kind = "json", source = rel, data = data }
end

-- A run folder: the run's record (run.md: title, label, name, link, ## Prompt) beside its files,
-- experiments.csv (the download, perhaps with review columns of its own) and results.json
-- (`asta autodiscovery results`). Both files are passed; the page draws from the results and
-- takes the CSV's own columns beside them.
local function is_run_folder(names)
  for _, n in ipairs(names or {}) do
    if n == "run.md" or n == "experiments.csv" or n == "results.json" or n:match("%.results%.json$") then return true end
  end
  return false
end

local function folder_run(dir, rel, names)
  local run = { kind = "folder", source = rel, runmd = read_file(pandoc.path.join({ dir, "run.md" })) }
  for _, n in ipairs(names) do
    local child, crel = pandoc.path.join({ dir, n }), rel .. "/" .. n
    if n == "results.json" or n:match("%.results%.json$") then
      run.results = file_run(child, crel)
    elseif n == "experiments.csv" then
      run.csv = read_file(child)
      run.csvSource = crel
    end
  end
  if has_nodes(names) then
    local nr = node_run(dir, rel)
    run.nodes, run.meta = nr.nodes, nr.meta
  end
  return run
end

-- The runs `data` names: one file, one local output folder or run folder, or a folder of them.
local function autods_runs(rel)
  rel = rel:gsub("/$", "")
  local path = pandoc.path.join({ page_dir(), rel })
  local names = list_dir(path)
  if names == nil then
    local run = file_run(path, rel)
    return run and { run } or nil
  end
  if is_run_folder(names) then return { folder_run(path, rel, names) } end
  if has_nodes(names) then return { node_run(path, rel) } end
  local runs = {}
  for _, name in ipairs(names) do
    local child, crel = pandoc.path.join({ path, name }), rel .. "/" .. name
    local lower = name:lower()
    local sub = list_dir(child)
    if sub ~= nil then
      if is_run_folder(sub) then runs[#runs + 1] = folder_run(child, crel, sub)
      elseif has_nodes(sub) then runs[#runs + 1] = node_run(child, crel) end
    elseif name:sub(1, 1) ~= "." and (lower:match("%.csv$") or lower:match("%.json$")) then
      runs[#runs + 1] = file_run(child, crel)
    end
  end
  return runs
end

local function autods(kwargs)
  if not quarto.doc.is_format("html") then
    return pandoc.Null()
  end
  add_deps("autods")
  local rel = pandoc.utils.stringify(kwargs["data"] or "")
  local err
  local runs = rel ~= "" and autods_runs(rel) or nil
  if rel == "" then
    err = "the shortcode names no run files; use data=\"autods\" (a folder) or a run's CSV."
  elseif runs == nil then
    err = "cannot read " .. rel .. ". Put the run's results (asta autodiscovery results), its download or its output folder there, then render again."
  elseif #runs == 0 then
    err = rel .. " holds no AutoDiscovery runs (no .csv or .json files, no mcts_node_*.json)."
  end
  if err then
    quarto.log.warning("asta-autods: " .. err)
    return pandoc.RawBlock("html",
      '<div class="asta-panel"><div class="ap-error">This page has no data yet: ' ..
      html_escape(err) .. '</div></div>')
  end
  local name = pandoc.utils.stringify(kwargs["name"] or "")
  if name ~= "" and #runs == 1 then runs[1].name = name end
  local text = quarto.json.encode({ format = "asta-pages/autods@1", runs = runs })
  local safe = text:gsub("</", "<\\/")
  return pandoc.RawBlock("html",
    '<div class="asta-panel asta-autods" data-asta-source="' .. html_escape(rel) .. '"></div>\n' ..
    '<script type="application/json" id="asta-autods-data">' .. safe .. '</script>')
end

local function workflow(kwargs)
  if not quarto.doc.is_format("html") then
    return pandoc.Null()
  end
  local rel = pandoc.utils.stringify(kwargs["file"] or "")
  if rel == "" then rel = "workflow.mmd" end
  local f = io.open(pandoc.path.join({ page_dir(), rel }), "r")
  local src = f and f:read("a")
  if f then f:close() end
  if src == nil or src:match("^%s*$") then
    return pandoc.Blocks({})
  end
  local title = pandoc.utils.stringify(kwargs["title"] or "")
  if title == "" then title = "Workflow" end
  local head = pandoc.Header(2, title, pandoc.Attr("workflow"))
  local share = os.getenv("QUARTO_SHARE_PATH")
  local dir = share and pandoc.path.join({ share, "formats", "html", "mermaid" })
  local probe = dir and io.open(pandoc.path.join({ dir, "mermaid.min.js" }), "r")
  if probe == nil then
    quarto.log.warning("asta-workflow: Quarto's Mermaid runtime was not found; showing the diagram source")
    return pandoc.Blocks({ head, pandoc.CodeBlock(src) })
  end
  probe:close()
  css_dep()
  quarto.doc.add_html_dependency({
    name = "asta-mermaid",
    version = "0.1.0",
    scripts = { pandoc.path.join({ dir, "mermaid.min.js" }), pandoc.path.join({ dir, "mermaid-init.js" }) },
    stylesheets = { pandoc.path.join({ dir, "mermaid.css" }) },
  })
  -- Mermaid draws the chart to the column's width. Once it has, let it be up to 1.6 times wider
  -- than the column (scrolling sideways) so a long chain keeps readable labels.
  local sizer = [[<script>(function (box) {
  function fit() {
    var svg = box.querySelector("svg"), vb = svg && svg.viewBox && svg.viewBox.baseVal;
    if (!vb || !vb.width) return false;
    var w = Math.min(vb.width, box.clientWidth * 1.6);
    svg.setAttribute("width", w); svg.style.maxWidth = "none"; svg.style.width = w + "px";
    return true;
  }
  if (!fit()) new MutationObserver(function (_, o) { if (fit()) o.disconnect(); }).observe(box, { childList: true, subtree: true });
})(document.currentScript.previousElementSibling);</script>]]
  return pandoc.Blocks({ head, pandoc.RawBlock("html",
    '<div class="cell asta-workflow"><pre class="mermaid mermaid-js">' .. html_escape(src) .. "</pre></div>" .. sizer) })
end

return {
  ["asta-workflow"] = function(args, kwargs, meta)
    return workflow(kwargs)
  end,
  ["asta-theories"] = function(args, kwargs, meta)
    return theories_panel(kwargs)
  end,
  ["asta-literature"] = function(args, kwargs, meta)
    return panel("literature", "literature", kwargs)
  end,
  ["asta-autods"] = function(args, kwargs, meta)
    return autods(kwargs)
  end,
}
