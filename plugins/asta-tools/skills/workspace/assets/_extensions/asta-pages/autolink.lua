-- asta-pages autolink: links in a page's text open a card of what they point at, and
-- mentions of tests, theories, gaps and experiments become such links.
--
-- The filter is the extension's, listed once in _quarto.yml; it runs on every page, after
-- Quarto has expanded the shortcodes and cross-references and before citations are formatted
-- (`at: pre-render`). `asta-autolink: false` in a page's front matter turns it off there:
--
--   filters:
--     - asta-pages
--
-- Mentions linked (the index is read when the page renders, from the workflow pages,
-- pages/*.qmd: their shortcodes and the files those name). Tests, theories, experiments and figures: the first mention in a paragraph; a
-- gap: the first in a section (heading to heading).
--
--   test ids          an asta-tests `dir` subfolder or `index` id   -> <page>#test-<id>
--   AutoDS node ids   a local run's mcts_node_<a>_<b>.json          -> <page>#node-<a>-<b>
--   theory names      an asta-theories theory, whatever its spacing and dashes -> its anchor
--   gaps              "G7": every theories tab with a theory whose `gap` is G7
--   "Experiment N"    an asta-autods run's experiment N              -> <page>#experiment-N
--                     (hosted: id_in_run N; local: creation_idx N + 1); a test index's
--                     `seed: {test_id, experiment}` (in older runs, a string
--                     "<id> (Experiment N …)"); and the hosted experiment a run was seeded
--                     from (its metadata's lineage), or a page link to it
--   "Figure N"        the page's figure N                           -> #fig-<id>
--
-- Links given a card as they are: external links (a paper: doi.org, semanticscholar.org or a
-- reference's URL; a dataset: one of a dataset's links in .asta/datasets.json; any other site),
-- citations ([@key], with the quote of an evidence claim in the same paragraph citing it; a
-- paper of the run's paper set links to it there, #paper-<corpus id or key>), evidence claims
-- ([...]{.ev}; asta-pages.js then shows this card instead of the evidence popover), figure
-- cross-references, links to the site's pages (pages/0001-x.qmd#experiment-3: the card of the
-- item the fragment names, never a file), and links to workspace files.
--
-- Every card is built here, as data: sections (a role, a title and its link, a sub line, a
-- thumbnail, text clamped to some lines, a quote, a test's verdict, tests' verdicts, a tally,
-- facts, links) and a footer. asta-pages.js draws any card the same way: a new kind of link
-- needs an adapter here and no card code. The page carries its cards once
-- (script.asta-cards-data, keyed); a link names its card (data-asta-card). A mention that
-- names several things (a node id that is both an AutoDS experiment and its reproduction
-- test) links to the test, else the theory, the experiment, the hosted experiment, the figure,
-- the gap, and its card lists each.

-- Lines of text a card shows for an AutoDS hypothesis, a theory's name and summary, and the theory a
-- test belongs to, before it is cut. Enough to read the claim, not just its opening words.
local DESCRIPTION_LINES = 4

local function load_lib()
  local env = setmetatable({}, { __index = _ENV })
  local chunk = assert(loadfile(quarto.utils.resolve_path("asta-pages.lua"), "t", env))
  chunk()
  return env.ASTA_PAGES_LIB
end

local L -- the shared helpers, once loaded
local here_dir -- the source page's folder

-- ---- the text a mention is matched on ------------------------------------------------------

local DASHES = { ["—"] = "-", ["–"] = "-", ["‒"] = "-", ["−"] = "-", ["‐"] = "-", ["‑"] = "-" }

local function chars(s)
  local out = {}
  for _, c in utf8.codes(s) do
    local ch = utf8.char(c)
    if DASHES[ch] then ch = "-" elseif ch:match("^%s$") or c == 0xA0 then ch = " " end
    out[#out + 1] = ch
  end
  return out
end

local function key_of(s)
  return (table.concat(chars(s)):gsub("%s+", " "):gsub("^ ", ""):gsub(" $", ""))
end

-- Letters, digits and "_" make a word (ASCII: an id or a name never runs into other scripts).
local function is_word(ch) return ch ~= nil and ch:match("^[%w_]$") ~= nil end

local function clip(s, n)
  s = tostring(s or ""):gsub("%s+", " "):gsub("^ ", "")
  local len = utf8.len(s)
  if len and len > n then s = s:sub(1, utf8.offset(s, n + 1) - 1):gsub("%s+%S*$", "") .. "…" end
  return s
end

local function first_sentence(s)
  s = tostring(s or ""):gsub("%s+", " "):gsub("^ ", "")
  return s:match("^(.-[%.!?])%s") or s
end

-- ---- the link index -----------------------------------------------------------------------

local index = {}   -- key -> { key = key, [kind] = target }
local maxlen = 0
local first_char = {}

local function add(key, target, kind)
  key = key_of(key)
  if key == "" then return end
  local e = index[key]
  if e == nil then
    index[key] = { key = key, [kind] = target }
    local n = #chars(key)
    if n > maxlen then maxlen = n end
    first_char[chars(key)[1]] = true
  elseif e[kind] == nil then
    e[kind] = target
  else
    -- The same place found twice (a page's link and a run's metadata): what each knows.
    for k, v in pairs(target) do if e[kind][k] == nil then e[kind][k] = v end end
  end
end

-- A mention of something a later page shows again: the first page keeps it, as it is.
local function add_new(key, target, kind)
  local e = index[key_of(key)]
  if e and e[kind] then return end
  add(key, target, kind)
end

-- What each workflow page's panels anchor: page source -> anchor -> { kind, target }. A link to
-- the page with that anchor (pages/0001-x.qmd#experiment-3) gets the item's card.
local items = {}

local function note_item(page, anchor, kind, target)
  if not page.src then return end
  local on = items[page.src] or {}
  items[page.src] = on
  if on[anchor] == nil then on[anchor] = { kind = kind, target = target } end
end

-- JSON read natively when Pandoc can (a hosted run's results are tens of MB), else as the
-- shared helpers read it.
local function fast_json(text)
  if type(text) ~= "string" then return nil end
  if pandoc.json and pandoc.json.decode then
    local ok, data = pcall(pandoc.json.decode, text, false)
    if ok and type(data) == "table" then return data end
  end
  return L.decode_json(text)
end

local function shortcodes(text)
  local out = {}
  for name, body in text:gmatch("{{<%s*(asta%-[%w%-]+)(.-)>}}") do
    local kw = {}
    for k, v in body:gmatch('([%w_%-]+)%s*=%s*"(.-)"') do kw[k] = v end
    for k, v in body:gmatch("([%w_%-]+)%s*=%s*([^%s\"]+)") do if kw[k] == nil then kw[k] = v end end
    out[#out + 1] = { name = name, kw = kw }
  end
  return out
end

local function test_anchor(id) return "test-" .. id:gsub("[^A-Za-z0-9_.-]+", "-") end

local tests_by_id = {}       -- test id -> { dir, entry }: what a test's card reads
local tests_by_theory = {}   -- theory name key -> { test ids }

local function note_test(id, dir, entry)
  local t = tests_by_id[id] or {}
  tests_by_id[id] = t
  t.dir = t.dir or dir
  if type(entry) == "table" then
    t.entry = t.entry or entry
    if type(entry.theory_name) == "string" then
      local k = key_of(entry.theory_name)
      tests_by_theory[k] = tests_by_theory[k] or {}
      local list = tests_by_theory[k]
      for _, x in ipairs(list) do if x == id then return end end
      list[#list + 1] = id
    end
  end
end

local function test_target(page, id)
  local t = { href = page.href .. "#" .. test_anchor(id), id = id, page = page.title }
  note_item(page, test_anchor(id), "test", t)
  return t
end

-- A test index may say which of its tests reproduces the experiment a run was seeded from:
-- `"seed": {"test_id": "H00", "experiment": 15}` at its top level. Older indexes said it in a
-- string, "H00 (Experiment 7 of the source run, the seed)".
local function index_seed_test(text, page)
  local data = L.decode_json(text)
  local seed = type(data) == "table" and not L.is_list(data) and data.seed
  if type(seed) == "table" and seed.test_id ~= nil and tonumber(seed.experiment) then
    add("Experiment " .. math.floor(tonumber(seed.experiment)), test_target(page, tostring(seed.test_id)), "test")
    return
  end
  for id, n in text:gmatch('"([%w_.%-]+) %((Experiment %d+)[^"]*%)"') do add(n, test_target(page, id), "test") end
end

-- An asta-tests panel's tests (or, entries_only, an asta-theories panel's test indexes: what
-- its theories' cards read).
local function index_tests(kw, page, entries_only)
  local dirs = {}
  for _, rel in ipairs(L.split_list((entries_only and kw.tests_dir or kw.dir) or "", ",")) do
    local abs = L.project_path(rel)
    if abs then dirs[#dirs + 1] = abs end
  end
  local function dir_of(id)
    for _, d in ipairs(dirs) do if L.is_dir(d .. "/" .. id) then return d .. "/" .. id end end
    return nil
  end
  if not entries_only then
    for _, abs in ipairs(dirs) do
      for _, n in ipairs(L.list_dir(abs) or {}) do
        if n:sub(1, 1) ~= "." and not L.skip_name(n) and L.is_dir(abs .. "/" .. n) then
          add(n, test_target(page, n), "test")
          note_test(n, abs .. "/" .. n, nil)
        end
      end
    end
  end
  for _, rel in ipairs(L.split_list((entries_only and kw.tests or kw.index) or "", ",")) do
    for _, e in ipairs(L.read_index(rel) or {}) do
      local id = e.test_id
      if not e.loose or dir_of(id) then
        if not entries_only then add(id, test_target(page, id), "test") end
        note_test(id, dir_of(id), e)
      end
    end
    local abs = L.project_path(rel:match("^(.-)#") or rel)
    local text = abs and L.read_file(abs)
    if text and not entries_only then index_seed_test(text, page) end
  end
end

local HOSTED = "https://autodiscovery.allen.ai/runs/shared/"

local function node_target(page, id, prefix, file)
  local a, b = id:match("^node_(%d+)_(%d+)$")
  local anchor = (prefix or "") .. "node-" .. a .. "-" .. b
  local t = { href = page.href .. "#" .. anchor, id = id, file = file, page = page.title }
  note_item(page, anchor, "run", t)
  return t
end

-- A file the run names by its path where it ran (args.json's dataset_metadata): the same path
-- in this project, found by its shortest tail that exists here.
local function local_file(path)
  if type(path) ~= "string" or path == "" then return nil end
  local parts = {}
  for seg in path:gmatch("[^/]+") do parts[#parts + 1] = seg end
  for i = 1, #parts do
    local abs = L.project_path(table.concat(parts, "/", i))
    if abs and L.read_file(abs) then return abs end
  end
  return nil
end

-- A seeded run's seed: its metadata's lineage names the hosted run and the experiment it
-- started from ("Experiment ID 7 (node_2_4)"), with that experiment's record beside it. Returns
-- the experiment's number.
local function index_seed(dir)
  local args = L.decode_json(L.read_file(dir .. "/args.json"))
  local meta_file = type(args) == "table" and local_file(args.dataset_metadata)
  local meta = meta_file and L.decode_json(L.read_file(meta_file))
  local lineage = type(meta) == "table" and type(meta.lineage) == "table" and meta.lineage
  if not lineage or type(lineage.parent_run_id) ~= "string" then return nil end
  local n = tostring(lineage.seed_experiment or ""):match("(%d+)")
  if not n then return nil end
  local base = pandoc.path.directory(meta_file)
  local record = nil
  for _, f in ipairs(L.list_dir(base) or {}) do
    if f:match("^source%-experiment%-" .. n .. "[%.%-_]") and f:match("%.json$") then record = base .. "/" .. f end
  end
  add("Experiment " .. n, { href = HOSTED .. lineage.parent_run_id .. "?exp=" .. n, external = true, n = n, file = record },
    "hosted")
  return n
end

-- ---- an AutoDS panel's experiments, numbered as autods.js numbers them ----------------------

-- The service writes every value as text ("None", "0.75").
local function num(v)
  if type(v) == "number" then return v end
  if type(v) == "string" then return tonumber(v) end
  return nil
end

local function slug(s) return (tostring(s or ""):gsub("[^%w]", "-"):lower()) end

-- A hosted run's experiments (`asta autodiscovery results`, the hosted Download -> JSON, or
-- the service's {experiments}): experiment N is its id_in_run, else its place in the list. And
-- the run's name, as a CSV download beside it is named.
local function json_experiments(path)
  local d = fast_json(L.read_file(path))
  local list = type(d) == "table" and (L.is_list(d) and d or d.experiments) or nil
  local out = {}
  for k, x in ipairs(type(list) == "table" and list or {}) do
    if type(x) == "table" then
      local raw = x.id_in_run
      if raw == nil then raw = x.idInRun end
      if raw == nil then raw = x.id end
      local id = math.floor(num(raw) or k)
      local key = x.experiment_id or x.experimentId
      out[#out + 1] = { id = id, key = type(key) == "string" and key ~= "" and key or nil, x = {
        n = id, hypothesis = type(x.hypothesis) == "string" and clip(x.hypothesis, 220) or nil,
        prior = num(x.prior), posterior = num(x.posterior), surprisal = num(x.surprise) or num(x.surprisal) } }
    end
  end
  local run = type(d) == "table" and type(d.run) == "table" and d.run or nil
  return out, run and type(run.name) == "string" and slug(run.name) or nil
end

-- A local run's node records (mcts_node_<a>_<b>.json): experiment N is creation_idx N + 1.
-- mcts_node_1_0 loads the dataset: the panel shows no experiment for it.
local function node_experiments(dir, names)
  local out = {}
  for _, n in ipairs(names) do
    local a, b = n:match("^mcts_node_(%d+)_(%d+)%.json$")
    if a and n ~= "mcts_node_1_0.json" then
      local file = dir .. "/" .. n
      local idx = tonumber((L.read_file(file) or ""):match('"creation_idx"%s*:%s*"?(%d+)'))
      out[#out + 1] = { id = idx and idx - 1 or nil, key = "node_" .. a .. "_" .. b, file = file }
    end
  end
  return out
end

local function is_run_folder(names)
  for _, n in ipairs(names) do
    if n == "run.md" or n == "experiments.csv" or n == "results.json" or n:match("%.results%.json$") then return true end
  end
  return false
end

-- A run folder (its results, else its node records) or a local output folder.
local function folder_experiments(dir, names)
  local nodes = L.has_nodes(names) and node_experiments(dir, names) or {}
  local exps = nil
  for _, n in ipairs(names) do
    if n == "results.json" or n:match("%.results%.json$") then exps = json_experiments(dir .. "/" .. n) end
  end
  return { experiments = exps or nodes, nodes = nodes }
end

-- The runs an asta-autods `data` names, as the shortcode finds them: one results file, one run
-- or output folder, or a folder of them. A CSV download is a run whose experiments are not read
-- here; one named like a results file beside it is that run, drawn once.
local function autods_experiments(abs)
  local names = L.list_dir(abs)
  if names == nil then
    if abs:lower():match("%.json$") then return { { experiments = json_experiments(abs), nodes = {} } } end
    return { { experiments = {}, nodes = {} } }
  end
  if is_run_folder(names) or L.has_nodes(names) then return { folder_experiments(abs, names) } end
  local runs, named = {}, {}
  for _, n in ipairs(names) do
    local child, lower = abs .. "/" .. n, n:lower()
    local sub = L.list_dir(child)
    if sub then
      if is_run_folder(sub) or L.has_nodes(sub) then runs[#runs + 1] = folder_experiments(child, sub) end
    elseif n:sub(1, 1) ~= "." and lower:match("%.json$") then
      local exps, name = json_experiments(child)
      named[name or slug(n:gsub("%.[Jj][Ss][Oo][Nn]$", ""):gsub("%.results$", ""))] = true
      runs[#runs + 1] = { experiments = exps, nodes = {} }
    elseif n:sub(1, 1) ~= "." and lower:match("%.csv$") then
      runs[#runs + 1] = { experiments = {}, nodes = {}, csv = n:gsub("%.[Cc][Ss][Vv]$", ""):gsub("_%d%d%d%d%-%d%d%-%d%d$", "") }
    end
  end
  local out = {}
  for _, r in ipairs(runs) do if not (r.csv and named[r.csv]) then out[#out + 1] = r end end
  return out
end

-- An asta-autods panel: its node ids (a local run's), and its experiments, "Experiment N" ->
-- <page>#experiment-N (#run-<n>/experiment-N with several runs; the first run, and the first
-- page by file name, wins). A seeded run's "Experiment N" of its seed is the hosted experiment.
local function index_autods(kw, page)
  local rel = kw.data or ""
  if rel == "" then return end
  local abs = L.normalize(page.dir .. "/" .. rel:gsub("/$", ""))
  local runs = autods_experiments(abs)
  local many = #runs > 1
  local seed = (not many) and L.is_dir(abs) and index_seed(abs) or nil
  for i, run in ipairs(runs) do
    local prefix = many and ("run-" .. i .. "/") or ""
    for _, x in ipairs(run.nodes) do add(x.key, node_target(page, x.key, prefix, x.file), "run") end
    for _, x in ipairs(run.experiments) do
      if x.id then
        local anchor = prefix .. "experiment-" .. x.id
        local t = { href = page.href .. "#" .. anchor, id = x.key, n = x.id, file = x.file, x = x.x, page = page.title }
        note_item(page, anchor, "run", t)
        if tostring(x.id) ~= seed then add_new("Experiment " .. x.id, t, "run") end
      end
    end
  end
end

local function stem_of(rel, i)
  local name = (rel:match("([^/]*)$") or ""):gsub("%.[Jj][Ss][Oo][Nn]$", ""):gsub("[^A-Za-z0-9_-]+", "-")
  return name ~= "" and name or ("source-" .. i)
end

local gap_tabs = {}   -- gap id -> { {href, page, question, theories = {names}} }

-- The run's papers: a paper list's (asta-literature) and the papers a theories panel's theories
-- reference (its Referenced papers tab). Corpus id, key, or a copy's -> { href, page, paper }.
local papers_lit, papers_th = {}, {}

-- A paper's id as literature.js and theories.js anchor it: its corpus id, else its key.
local function id_text(v)
  if type(v) == "string" and v ~= "" then return v end
  if type(v) == "number" then return string.format("%d", math.floor(v)) end
  return nil
end

local function note_paper(store, page, p)
  local base = id_text(p.corpusId) or id_text(p.key)
  if not base then return end
  local anchor = "paper-" .. base
  local t = { href = page.href .. "#" .. L.url_path(anchor), page = page.title, paper = p }
  note_item(page, anchor, "paper", t)
  local function put(id) if id and store[id] == nil then store[id] = t end end
  put(id_text(p.corpusId))
  put(id_text(p.key))
  for _, c in ipairs(type(p.duplicates) == "table" and p.duplicates or {}) do
    if type(c) == "table" then put(id_text(c.corpusId)); put(id_text(c.key)) end
  end
end

-- The paper a citation names: its key is s2-<corpus id> (theorizer-site-data --bib writes it),
-- or a paper's own key. A paper list first, then a theory's papers; the first page by file name.
local function paper_of_cite(id)
  local ids = { id }
  local corpus = id:match("^s2%-(%d+)$")
  if corpus then table.insert(ids, 1, corpus) end
  for _, store in ipairs({ papers_lit, papers_th }) do
    for _, k in ipairs(ids) do if store[k] then return store[k] end end
  end
  return nil
end

-- An asta-literature panel: every paper it lists, at #paper-<corpus id or key>.
local function index_literature(kw, page)
  local rel = kw.data or ""
  if rel == "" then return end
  local data = fast_json(L.read_file(L.normalize(page.dir .. "/" .. rel)))
  local list = type(data) == "table" and data.papers
  for _, p in ipairs(type(list) == "table" and list or {}) do
    if type(p) == "table" then note_paper(papers_lit, page, p) end
  end
end

-- A theory's gap is its `gap` field, or its data file's (theorizer-site-data --gap G7). A
-- theories tab belongs to every gap one of its theories names.
local function gap_of(t, data)
  local g = type(t.gap) == "string" and t.gap or (type(data.gap) == "string" and data.gap) or nil
  return g and g ~= "" and g or nil
end

-- The theories panel's anchors, as theories.js gives them: a theory's id ("theory-N"); when a
-- later file uses the same id, "<file stem>/theory-N" (then "-2", "-3" ...). Queries are its
-- tabs, in the order they first appear.
local function index_theories(kw, page)
  local seen, anchors, queries, nq = {}, {}, {}, 0
  for i, rel in ipairs(L.split_list(kw.data or "", ",")) do
    local text = L.read_file(L.normalize(page.dir .. "/" .. rel))
    local data = text and L.decode_json(text)
    local stem = stem_of(rel, i)
    -- Its papers, by key and a copy's key, as theories.js finds them.
    local by_key = {}
    local plist = type(data) == "table" and type(data.papers) == "table" and data.papers or {}
    for _, p in ipairs(plist) do
      for _, c in ipairs(type(p) == "table" and type(p.duplicates) == "table" and p.duplicates or {}) do
        if type(c) == "table" and c.key ~= nil and by_key[c.key] == nil then by_key[c.key] = p end
      end
    end
    for _, p in ipairs(plist) do if type(p) == "table" and p.key ~= nil then by_key[p.key] = p end end
    for _, t in ipairs(type(data) == "table" and type(data.theories) == "table" and data.theories or {}) do
      local id, name = tostring(t.id), tostring(t.name or "")
      local k = id .. "\0" .. name
      if not seen[k] then
        seen[k] = true
        local base = id:match("^theory%-") and id or ("theory-" .. id)
        local anchor = base
        if anchors[anchor] then anchor = stem .. "/" .. base end
        local n = 2
        while anchors[anchor] do anchor = stem .. "/" .. base .. "-" .. n; n = n + 1 end
        anchors[anchor] = true
        local target = { href = page.href .. "#" .. anchor, page = page.title, name = name,
          summary = type(t.summary) == "string" and t.summary or nil,
          supporting = tonumber(t.supporting), conflicting = tonumber(t.conflicting) }
        note_item(page, anchor, "theory", target)
        if name ~= "" then add_new(name, target, "theory") end
        for _, pk in ipairs(type(t.papers) == "table" and t.papers or {}) do
          if by_key[pk] then note_paper(papers_th, page, by_key[pk]) end
        end
        local q = tostring(t.query or data.request or ""):gsub("%s+", " "):gsub("^ ", ""):gsub(" $", "")
        if queries[q] == nil then
          nq = nq + 1
          queries[q] = { n = nq, theories = {}, gaps = {} }
        end
        table.insert(queries[q].theories, name)
        local gap = gap_of(t, data)
        if gap and not queries[q].gaps[gap] then
          queries[q].gaps[gap] = true
          gap_tabs[gap] = gap_tabs[gap] or {}
          -- The question, without the gap's own name in front of it ("G1 (weighted): …").
          local question = q
          if q:sub(1, #gap) == gap then question = q:gsub("^[^:]*:%s*", "") end
          table.insert(gap_tabs[gap], { href = page.href .. "#query-" .. queries[q].n, page = page.title,
            question = question, theories = queries[q].theories })
          add(gap, { id = gap }, "gap")
        end
      end
    end
  end
  index_tests(kw, page, true)
end

local doc_entries = {} -- entry id -> { href, page }: a heading or list item of an inline document
-- that starts with that id (asta-doc anchors it); a gap's card links the entry of its id

local function index_doc(kw, page)
  local abs, clean = L.project_path(kw.file or "")
  local text = abs and L.read_file(abs)
  if not text then return end
  local ok, doc = pcall(pandoc.read, text, "markdown-citations")
  if not ok then return end
  -- Its entries, as asta-doc anchors them: a heading, or a list item that starts with an id.
  local slug = clean:lower():gsub("[^%w]+", "-")
  local function note(id, anchor)
    if id and not doc_entries[id] then doc_entries[id] = { href = page.href .. "#doc-" .. slug .. "-" .. anchor, page = page.title } end
  end
  local function list(l)
    for _, item in ipairs(l.content) do
      local first = item[1]
      local id = first and (first.t == "Plain" or first.t == "Para") and L.entry_id(pandoc.utils.stringify(first))
      if id then note(id, id:lower()) end
    end
  end
  doc.blocks:walk({
    Header = function(h)
      local id = L.entry_id(pandoc.utils.stringify(h.content))
      if id and h.identifier ~= "" then note(id, h.identifier) end
    end,
    BulletList = list,
    OrderedList = list,
  })
end

local site_pages = {} -- the pages the project renders (its render list): never workspace files

local function build(meta)
  for _, p in ipairs(L.render_list()) do site_pages[L.normalize(p)] = true end
  local pages = {}
  for _, src in ipairs(L.workflow_pages()) do pages[#pages + 1] = src end
  for _, src in ipairs(pages) do
    local text = L.read_file(src) or ""
    local fm = L.front_matter(src) or {}
    local page = {
      src = L.normalize(src),
      dir = pandoc.path.directory(src),
      title = L.meta_text(fm.title) ~= "" and L.meta_text(fm.title) or pandoc.path.filename(src),
      href = L.url_path(L.relative(L.rendered_file(src), L.rendered_dir())),
    }
    for _, sc in ipairs(shortcodes(text)) do
      if sc.name == "asta-tests" then index_tests(sc.kw, page)
      elseif sc.name == "asta-autods" then index_autods(sc.kw, page)
      elseif sc.name == "asta-theories" then index_theories(sc.kw, page)
      elseif sc.name == "asta-literature" then index_literature(sc.kw, page)
      elseif sc.name == "asta-doc" then index_doc(sc.kw, page) end
    end
  end
end

-- ---- what this page itself holds: figures, dataset tables, references --------------------

local figures = {}      -- figure id -> { n, src, caption }
local datasets = {}     -- url -> { name, by, used }
local refs = {}         -- citation id -> CSL item
local refs_by_url = {}  -- normalized URL, or "doi:" DOI -> CSL item

local function norm_url(u)
  return (tostring(u or ""):lower():gsub("^https?://", ""):gsub("^www%.", ""):gsub("/+$", ""))
end

local function str(v) return v ~= nil and pandoc.utils.stringify(v) or nil end

local function scan_page(doc)
  local ok, list = pcall(pandoc.utils.references, doc)
  for _, r in ipairs(ok and list or {}) do
    refs[r.id] = r
    local url, doi = str(r.URL or r.url), str(r.DOI or r.doi)
    if url then refs_by_url[norm_url(url)] = r end
    if doi then refs_by_url["doi:" .. doi:lower()] = r end
  end
  -- Figures, as the page's source writes them (Quarto keeps its own form of them until it
  -- renders): each `::: {#fig-…}` block, numbered in order as Quarto numbers figures (a figure
  -- inside another is a sub-figure, not numbered), its first image, and its caption, the last
  -- paragraph of the block.
  local src_ok, src_doc = pcall(pandoc.read, L.read_file(quarto.doc.input_file) or "", "markdown")
  local nfig = 0
  local function figs(blocks, inside)
    for _, b in ipairs(blocks) do
      if b.t == "Div" then
        local is_fig = b.identifier:match("^fig%-") ~= nil
        if is_fig and not inside then
          nfig = nfig + 1
          local img, caption = nil, ""
          b:walk({ Image = function(i) img = img or i.src end })
          for k = #b.content, 1, -1 do
            if b.content[k].t == "Para" then caption = pandoc.utils.stringify(b.content[k]); break end
          end
          -- Its sub-figures (with their first images), for its provenance when it has none.
          local subs = {}
          for _, c in ipairs(b.content) do
            if c.t == "Div" and c.identifier:match("^fig%-") then
              local si = nil
              c:walk({ Image = function(i) si = si or i.src end })
              subs[#subs + 1] = { id = c.identifier, src = si }
            end
          end
          figures[b.identifier] = { n = tostring(nfig), src = img, caption = caption, subs = subs }
        end
        figs(b.content, inside or is_fig)
      elseif b.content and type(b.content) == "table" and (b.t == "BlockQuote") then
        figs(b.content, inside)
      end
    end
  end
  if src_ok then figs(src_doc.blocks, false) end
  -- The workspace's datasets (.asta/datasets.json: [{id, name, released_by, used_for, links:
  -- [{label, url}]}]): a link to one of a dataset's links is that dataset.
  local ds = L.decode_json(L.read_file(L.project_path(".asta/datasets.json") or ""))
  for _, d in ipairs(L.is_list(ds) and ds or {}) do
    if type(d) == "table" then
      local rec = { name = d.name, by = d.released_by, used = d.used_for }
      for _, l in ipairs(L.is_list(d.links) and d.links or {}) do
        if type(l) == "table" and type(l.url) == "string" then datasets[norm_url(l.url)] = datasets[norm_url(l.url)] or rec end
      end
    end
  end
  for id, f in pairs(figures) do add("Figure " .. f.n, { href = "#" .. id, id = id }, "figure") end
end

-- ---- cards ---------------------------------------------------------------------------------

local cards, ncards = {}, 0   -- key -> card: the page's store

local function card(key, make)
  if cards[key] == nil then
    local c = make()
    cards[key] = c or false
    if c then ncards = ncards + 1 end
  end
  return cards[key] and key or nil
end

local SCORE = { definitely_false = 0, maybe_false = 0.25, uncertain = 0.5, maybe_true = 0.75, definitely_true = 1 }
local function belief(b)
  if type(b) ~= "table" then return nil end
  local p = b.prior_params
  if type(p) ~= "table" or #p < 2 then return type(b.mean) == "number" and b.mean or nil end
  local a, be = tonumber(p[1]) or 0, tonumber(p[2]) or 0
  for k, w in pairs(SCORE) do
    local n = tonumber(b[k]) or 0
    a, be = a + n * w, be + n * (1 - w)
  end
  return (a > 0 and be > 0) and a / (a + be) or nil
end

local function fmt(x) return x and string.format("%.2f", x) or nil end

local function experiment_of(file)
  local n = file and L.decode_json(L.read_file(file))
  if type(n) ~= "table" then return {} end
  return { hypothesis = clip(n.hypothesis, 220), prior = belief(n.prior), posterior = belief(n.posterior),
    surprisal = tonumber(n.normalized_surprisal), n = tonumber(n.creation_idx) and (tonumber(n.creation_idx) - 1) or nil }
end

local function experiment_facts(x)
  local facts = {}
  if x.prior and x.posterior then facts[#facts + 1] = "belief " .. fmt(x.prior) .. " → " .. fmt(x.posterior) end
  if x.surprisal then facts[#facts + 1] = "surprisal " .. fmt(x.surprisal) end
  return #facts > 0 and facts or nil
end

local function summary_of(dir)
  for _, f in ipairs(dir and L.summary_files or {}) do
    local d = L.decode_json(L.read_file(dir .. "/" .. f))
    if type(d) == "table" and not L.is_list(d) then return L.slim_summary(d) end
  end
  return nil
end

local function test_data(id)
  local t = tests_by_id[id] or {}
  return { id = id, summary = summary_of(t.dir), missing = (not t.dir) or nil }
end

-- What a verdict is read from (tests.js's verdict()), for a chip or a tally: not the numbers.
local VERDICT_KEYS = { "verdict", "ran", "runnable", "status" }
local function verdict_data(id)
  local full = test_data(id)
  local s = full.summary
  if type(s) ~= "table" then return full end
  local slim = {}
  for _, k in ipairs(VERDICT_KEYS) do slim[k] = s[k] end
  local m = s.meets_threshold
  if type(m) == "table" then
    slim.meets_threshold = {}
    for k, v in pairs(m) do if type(v) == "boolean" then slim.meets_threshold[k] = v end end
  else
    slim.meets_threshold = m
  end
  return { id = id, summary = slim, missing = full.missing }
end

-- The adapters: each turns what the index knows of one place into a section of a card.
local ADAPT = {}

function ADAPT.run(t)
  local x = t.x or experiment_of(t.file)
  local n = x.n or t.n
  local title = n and ("Experiment " .. n) or ""
  if t.id then title = title .. (n and " · " or "") .. t.id end
  return { role = "Discovery", title = title, href = t.href,
    sub = t.page, text = x.hypothesis, clamp = DESCRIPTION_LINES, facts = experiment_facts(x) }
end

function ADAPT.hosted(t)
  local x = experiment_of(t.file)
  return { role = "Discovery", title = "Experiment " .. t.n .. " on AutoDiscovery", href = t.href, external = true,
    text = x.hypothesis, clamp = DESCRIPTION_LINES, facts = experiment_facts(x) }
end

function ADAPT.test(t)
  local e = (tests_by_id[t.id] or {}).entry or {}
  local facts, theory = {}, nil
  if type(e.dataset) == "string" and e.dataset ~= "" then facts[#facts + 1] = "dataset " .. e.dataset end
  if type(e.theory_name) == "string" and e.theory_name ~= "" then
    theory = "Tests " .. e.theory_name .. (type(e.kind) == "string" and e.kind ~= "" and (" (" .. e.kind .. ")") or "")
  end
  return { role = "Verification", title = "Test " .. t.id, href = t.href, sub = t.page, test = test_data(t.id),
    facts = #facts > 0 and facts or nil, text = theory, clamp = DESCRIPTION_LINES }
end

function ADAPT.theory(t)
  local tests = {}
  for _, id in ipairs(tests_by_theory[key_of(t.name)] or {}) do tests[#tests + 1] = verdict_data(id) end
  local facts = {}
  if t.supporting then facts[#facts + 1] = math.floor(t.supporting) .. " supporting" end
  if t.conflicting then facts[#facts + 1] = math.floor(t.conflicting) .. " conflicting findings" end
  return { role = "Theory", title = t.name, title_clamp = DESCRIPTION_LINES, href = t.href, sub = t.page,
    tests = #tests > 0 and tests or nil, facts = #facts > 0 and facts or nil,
    text = t.summary and clip(t.summary, 600) or nil, clamp = DESCRIPTION_LINES }
end

-- A paper of the run's paper set (a link to its place in the list): title, authors, year, venue.
function ADAPT.paper(t)
  local p = t.paper
  local names = {}
  for i, a in ipairs(type(p.authors) == "table" and p.authors or {}) do
    if i > 3 then names[#names] = names[#names] .. " et al."; break end
    names[#names + 1] = type(a) == "table" and tostring(a.name or "") or tostring(a)
  end
  local sub = {}
  if #names > 0 then sub[#sub + 1] = table.concat(names, ", ") end
  if id_text(p.year) then sub[#sub + 1] = id_text(p.year) end
  if type(p.venue) == "string" and p.venue ~= "" then sub[#sub + 1] = p.venue end
  return { role = "Paper", title = type(p.title) == "string" and p.title or "Untitled", title_clamp = 2, href = t.href,
    sub = #sub > 0 and table.concat(sub, " · ") or nil }
end

-- A figure: its thumbnail, its caption's first sentence, n where the caption states a single
-- n, and the audit's verdict when the image's folder, or a step folder of .asta/flows named
-- for the figure, holds an audit.json with a `verdict`.
local function audit_of(id, src)
  local tries = {}
  if src and not src:match("^%a[%w+.-]*:") then
    local here = pandoc.path.directory(L.absolute(quarto.doc.input_file))
    tries[#tries + 1] = L.normalize(here .. "/" .. pandoc.path.directory(src) .. "/audit.json")
  end
  local flows = L.project_path(".asta/flows")
  for _, flow in ipairs(flows and L.list_dir(flows) or {}) do
    for _, step in ipairs(L.list_dir(flows .. "/" .. flow) or {}) do
      tries[#tries + 1] = flows .. "/" .. flow .. "/" .. step .. "/" .. id .. "/audit.json"
    end
  end
  for _, f in ipairs(tries) do
    local d = L.decode_json(L.read_file(f))
    if type(d) == "table" and type(d.verdict) == "string" then return d.verdict end
  end
  return nil
end

function ADAPT.figure(t)
  local f = figures[t.id]
  if not f then return nil end
  local facts, ns = {}, {}
  for n in f.caption:gmatch("%f[%w][nN]%s*=%s*(%d+)") do ns[#ns + 1] = n end
  if #ns == 1 then facts[#facts + 1] = "n = " .. ns[1] end
  -- What it was made from (figure.json): its script, its first inputs, its audit; for a figure
  -- of sub-figures, those of each sub-figure that has one, marked (a), (b) ...
  local links, verdict = {}, nil
  local function image_abs(src)
    if not src or src:match("^%a[%w+.-]*:") or src:match("^/") then return nil end
    return L.normalize(here_dir .. "/" .. L.url_decode(src))
  end
  local function add_links(p, mark)
    if p.script and not p.script.missing then links[#links + 1] = { label = mark .. p.script.name, href = p.script.href } end
    local shown, rest = 0, 0
    for _, it in ipairs(p.inputs) do
      if not it.missing and not it.outside then
        if shown < 3 then links[#links + 1] = { label = it.name, href = it.href }; shown = shown + 1 else rest = rest + 1 end
      end
    end
    if rest > 0 then links[#links + 1] = { label = "+" .. rest .. " more", href = p.folder } end
    if p.audit and not p.audit.missing then
      links[#links + 1] = { label = "audit" .. (p.verdict and (" " .. p.verdict) or ""), href = p.audit.href }
    end
    verdict = verdict or p.verdict
  end
  local own = L.figure_provenance(t.id, image_abs(f.src), true)
  if own then add_links(own, "")
  else
    for k, sub in ipairs(f.subs or {}) do
      local p = L.figure_provenance(sub.id, image_abs(sub.src), true)
      if p then add_links(p, "(" .. string.char(96 + k) .. ") ") end
    end
  end
  verdict = verdict or audit_of(t.id, f.src)
  if verdict then facts[#facts + 1] = "audit: " .. verdict end
  return { role = "Figure", title = "Figure " .. f.n, href = "#" .. t.id, image = f.src,
    text = first_sentence(f.caption), clamp = 3, facts = #facts > 0 and facts or nil, links = #links > 0 and links or nil }
end

-- A gap: each of its theories tabs (its question, how many theories, a tally of their tests),
-- and its entry in the gap map.
local function gap_sections(id)
  local out = {}
  for _, tab in ipairs(gap_tabs[id] or {}) do
    local tests = {}
    for _, name in ipairs(tab.theories) do
      for _, tid in ipairs(tests_by_theory[key_of(name)] or {}) do tests[#tests + 1] = verdict_data(tid) end
    end
    out[#out + 1] = { role = #out == 0 and ("Gap " .. id) or nil, title = tab.question, title_clamp = 1, href = tab.href,
      sub = tab.page, facts = { #tab.theories .. (#tab.theories == 1 and " theory" or " theories") },
      tally = #tests > 0 and tests or nil }
  end
  local entry = doc_entries[id]
  if entry then out[#out + 1] = { links = { { label = "Gap map entry", href = entry.href } } } end
  return out
end

local ORDER = { "hosted", "run", "test", "theory", "figure", "gap" }
local PRIMARY = { "test", "theory", "run", "hosted", "figure", "gap" }
local GOES = { test = "the test", run = "the experiment", hosted = "the experiment", theory = "the theory",
  gap = "the theories", figure = "the figure" }

local function primary_of(e)
  for _, k in ipairs(PRIMARY) do if e[k] then return k end end
end

local function kinds_of(e)
  local n = 0
  for _, k in ipairs(ORDER) do if e[k] then n = n + 1 end end
  return n
end

local function mention_card(e, text)
  return card("m:" .. e.key, function()
    local sections = {}
    for _, kind in ipairs(ORDER) do
      local t = e[kind]
      if t then
        if kind == "gap" then
          for _, s in ipairs(gap_sections(t.id)) do sections[#sections + 1] = s end
        else
          sections[#sections + 1] = ADAPT[kind](t)
        end
      end
    end
    if #sections == 0 then return nil end
    return { text = text, sections = sections,
      foot = kinds_of(e) > 1 and ("Clicking " .. text .. " opens " .. GOES[primary_of(e)] .. ".") or nil }
  end)
end

-- A reference: title, authors, year and venue, and its Semantic Scholar and DOI links.
local function authors_of(r)
  local names = {}
  for i, a in ipairs(r.author or {}) do
    if i > 3 then names[#names] = names[#names] .. " et al."; break end
    local fam, giv = str(a.family), str(a.given)
    names[#names + 1] = fam and (giv and (giv .. " " .. fam) or fam) or str(a.literal) or ""
  end
  return table.concat(names, ", ")
end

local function year_of(r)
  local issued = r.issued
  if type(issued) == "table" then
    local dp = issued["date-parts"]
    if type(dp) == "table" and type(dp[1]) == "table" and dp[1][1] then return str(dp[1][1]) end
    if issued.literal then return str(issued.literal) end
  end
  return issued and (str(issued) or ""):match("%d%d%d%d") or nil
end

local function ref_section(r, role)
  local sub = {}
  local au = authors_of(r)
  if au ~= "" then sub[#sub + 1] = au end
  local y = year_of(r)
  if y then sub[#sub + 1] = y end
  local venue = str(r["container-title"])
  if venue and venue ~= "" then sub[#sub + 1] = venue end
  local links, url, doi = {}, str(r.URL or r.url), str(r.DOI or r.doi)
  if url and url:match("semanticscholar%.org") then links[#links + 1] = { label = "Semantic Scholar", href = url, external = true } end
  if doi then links[#links + 1] = { label = "DOI", href = "https://doi.org/" .. doi, external = true } end
  if #links == 0 and url then links[#links + 1] = { label = "Source", href = url, external = true } end
  return { role = role or "Paper", title = str(r.title) or r.id, title_clamp = 2, sub = table.concat(sub, " · "),
    links = #links > 0 and links or nil }
end

local function citation_card(id, quotes)
  local r = refs[id]
  if not r then return nil end
  local qs = {}
  for i, q in ipairs(quotes or {}) do if i <= 2 then qs[#qs + 1] = q end end
  return card("c:" .. id .. ":" .. #qs .. ":" .. (qs[1] or ""):sub(1, 40), function()
    local sections = {}
    for i, q in ipairs(qs) do sections[#sections + 1] = { role = i == 1 and "Evidence" or nil, quote = q, clamp = 4 } end
    sections[#sections + 1] = ref_section(r)
    return { text = id, sections = sections }
  end)
end

-- An external link: a paper (by DOI, Semantic Scholar or a reference's URL), a dataset (a row
-- of the page's dataset table), or any site.
local function external_card(url, text)
  return card("x:" .. url, function()
    local doi = url:match("^https?://[%w%.]*doi%.org/(.+)$")
    local r = refs_by_url[norm_url(url)] or (doi and refs_by_url["doi:" .. doi:lower()])
    if r then return { text = text, sections = { ref_section(r) }, foot = "Opens in a new tab." } end
    local d = datasets[norm_url(url)]
    if d and d.name then
      return { text = text, sections = { { role = "Dataset", title = d.name, title_clamp = 2,
        sub = d.by and ("Released by " .. d.by) or nil, text = d.used and ("Used for: " .. d.used) or nil, clamp = 3 } },
        foot = "Opens in a new tab." }
    end
    local host = (url:match("^%a+://([^/:?#]+)") or url):gsub("^www%.", "")
    return { text = text, sections = { { role = host, title = text ~= "" and text or url, title_clamp = 2 } },
      foot = "Opens in a new tab." }
  end)
end

-- A workspace file (outside the site): its name (linked to the file, like the mention), folder and size. asta-pages.js says where it
-- opens: the app's Files tab, or GitHub once a deployed site's links point there. `from` is the
-- folder the link is relative to (the rendered page's for an inline document's raw links, the
-- source page's for links in the text).
local function file_card(href, from)
  local path = href:match("^([^#?]*)")
  if path == "" or path:match("^%a[%w+.-]*:") or path:match("^/") or path:match("%.html$") then return nil end
  local abs = L.normalize(from .. "/" .. L.url_decode(path))
  local rel = L.relative(abs, L.project_root())
  if rel:match("^%.%.") then return nil end
  local site = L.site_root()
  if site and abs:sub(1, #site + 1) == site .. "/" then return nil end
  if site_pages[abs] then return nil end
  local folder = path:match("/$") ~= nil
  local size = (not folder) and L.file_size(abs) or nil
  if not folder and not size then return nil end
  return card("f:" .. rel, function()
    local name = rel:gsub("/$", ""):match("([^/]+)$") or rel
    local dir = pandoc.path.directory((rel:gsub("/$", "")))
    return { text = name, file = true, sections = { { role = folder and "Folder" or "File", title = name .. (folder and "/" or ""),
      href = href, sub = dir ~= "." and dir or nil, facts = size and { L.human_size(size) } or nil } } }
  end)
end

-- A link to a page of the site (a .qmd or .md the project renders) is never a file. With a
-- fragment that names an item of that page's panels (#experiment-3, #theory-2, #test-T1,
-- #paper-123), it opens the item's card; else it is a plain page link. Returns whether it is a
-- page of the site, the card, and the rendered page's link (for raw HTML, which Quarto leaves).
local function page_link(href, from, text)
  local path = href:match("^([^#?]*)")
  local frag = L.url_decode(href:match("#(.*)$") or "")
  if path:match("^%a[%w+.-]*:") or path:match("^/") then return false end
  local abs = path == "" and L.normalize(L.absolute(quarto.doc.input_file)) or L.normalize(from .. "/" .. L.url_decode(path))
  if not site_pages[abs] then return false end
  local rendered = L.url_path(L.relative(L.rendered_file(abs), L.rendered_dir())) .. (frag ~= "" and ("#" .. L.url_path(frag)) or "")
  local it = frag ~= "" and items[abs] and items[abs][frag]
  if not it then return true, nil, rendered end
  local key = card("p:" .. L.relative(abs, L.project_root()) .. "#" .. frag, function()
    local s = ADAPT[it.kind](it.target)
    return s and { text = text, sections = { s } } or nil
  end)
  return true, key, rendered
end

-- ---- linking a page's text ---------------------------------------------------------------

local counts = {}
local function count(kind) counts[kind] = (counts[kind] or 0) + 1 end

local function card_attrs(key)
  return { { "data-asta-card", key }, { "aria-haspopup", "dialog" } }
end

local function link_for(e, words)
  local primary = primary_of(e)
  local text = pandoc.utils.stringify(words)
  local key = mention_card(e, text)
  local href = e[primary].href
  if primary == "gap" then
    local tabs = gap_tabs[e.gap.id]
    href = tabs and tabs[1] and tabs[1].href or "#"
  end
  count(kinds_of(e) > 1 and "several" or primary)
  local classes = { "asta-al" }
  if kinds_of(e) > 1 then classes[2] = "asta-al-many" end
  return pandoc.List({ pandoc.Link(words, href, "", pandoc.Attr("", classes, key and card_attrs(key) or {})) })
end

-- The Str/Space/SoftBreak run with its mentions linked. `done` holds what was already linked in
-- this paragraph, `section` what was linked in this section (gaps).
local function link_run(run, done, section)
  local text, tok, orig = {}, {}, {}
  for t, el in ipairs(run) do
    if el.t == "Str" then
      for _, c in utf8.codes(el.text) do
        local ch = utf8.char(c)
        text[#text + 1] = DASHES[ch] or ((ch:match("^%s$") or c == 0xA0) and " " or ch)
        tok[#tok + 1], orig[#orig + 1] = t, ch
      end
    else
      text[#text + 1], tok[#tok + 1], orig[#orig + 1] = " ", t, ""
    end
  end
  local matches, i = {}, 1
  while i <= #text do
    local hit = nil
    local prev, prev2 = text[i - 1], text[i - 2]
    if first_char[text[i]] and not is_word(prev) and not (prev == "-" and is_word(prev2)) then
      local buf = {}
      for j = i, math.min(#text, i + maxlen - 1) do
        buf[#buf + 1] = text[j]
        local e = index[table.concat(buf)]
        if e then
          local nx, nx2 = text[j + 1], text[j + 2]
          if not is_word(nx) and not ((nx == "-" or nx == ".") and is_word(nx2)) then hit = { i, j, e } end
        end
      end
    end
    if hit then matches[#matches + 1] = hit; i = hit[2] + 1 else i = i + 1 end
  end
  if #matches == 0 then return run end
  local out = pandoc.List()
  local function emit(a, b)
    local k = a
    while k <= b do
      local el = run[tok[k]]
      if el.t ~= "Str" then
        out:insert(el)
        k = k + 1
      else
        local piece, t = {}, tok[k]
        while k <= b and tok[k] == t do piece[#piece + 1] = orig[k]; k = k + 1 end
        out:insert(pandoc.Str(table.concat(piece)))
      end
    end
  end
  local at = 1
  for _, m in ipairs(matches) do
    local a, b, e = m[1], m[2], m[3]
    -- A gap alone is linked once a section; anything else once a paragraph.
    local seen = primary_of(e) == "gap" and section or done
    if seen[e.key] then
      emit(at, b)
    else
      seen[e.key] = true
      emit(at, a - 1)
      local before = #out
      emit(a, b)
      local words = pandoc.List()
      for k = before + 1, #out do words:insert(out[k]) end
      for _ = before + 1, #out do out:remove() end
      out:extend(link_for(e, words))
    end
    at = b + 1
  end
  emit(at, #text)
  return out
end

-- An evidence claim's quote, and the citation its source names (the evidence filter's markup:
-- .ev > .ev-pop > .ev-card > .ev-quote, .ev-pop-src).
local function ev_parts(span)
  local quote, cite, src = nil, nil, nil
  span:walk({
    Span = function(s)
      if s.classes:includes("ev-quote") and not quote then
        -- Evidence prints its quote marks; the card prints its own.
        quote = pandoc.utils.stringify(s):gsub("^%s+", ""):gsub("%s+$", "")
        for _, m in ipairs({ { "“", "”" }, { '"', '"' } }) do
          if quote:sub(1, #m[1]) == m[1] and quote:sub(-#m[2]) == m[2] then quote = quote:sub(#m[1] + 1, -#m[2] - 1) end
        end
      end
      if s.classes:includes("ev-pop-src") and not src then src = pandoc.utils.stringify(s) end
    end,
    Cite = function(c) cite = cite or c.citations[1].id end,
  })
  return quote, cite, src
end

local function ev_card(span)
  local quote, cite, src = ev_parts(span)
  if not quote then return nil end
  return card("e:" .. (span.attributes.key or quote:sub(1, 60)), function()
    local sections = { { role = "Evidence", quote = quote, clamp = 4 } }
    local r = cite and refs[cite]
    if r then sections[#sections + 1] = ref_section(r)
    elseif src and src ~= "" then sections[#sections + 1] = { role = "Source", title = src } end
    return { text = "claim", sections = sections }
  end)
end

local function ev_quotes(inl)
  local by = {}
  for _, el in ipairs(inl) do
    if el.t == "Span" and el.classes:includes("ev") then
      local quote, cite = ev_parts(el)
      if quote and cite then by[cite] = by[cite] or {}; table.insert(by[cite], quote) end
    end
  end
  return by
end

local CONTAINERS = { Emph = true, Strong = true, Underline = true, Strikeout = true, Superscript = true,
  Subscript = true, SmallCaps = true, Quoted = true, Span = true }

local walk_blocks

-- A link written as raw HTML (an inline document's links to workspace files): its card.
local function attach_raw(el)
  local href = el.text:match('^<a%s+href="([^"]+)"')
  if not href or el.text:match("data%-asta%-card") then return el end
  local is_page, pkey, rendered = page_link(href, L.rendered_dir(), nil)
  if is_page then
    -- Quarto turns a page's source into its .html in the text, not in raw HTML.
    el.text = el.text:gsub('^<a%s+href="[^"]+"', function() return '<a href="' .. rendered .. '"' end, 1)
    if not pkey then return el end
    count("page")
    el.text = el.text:gsub('%s+title="[^"]*"', ""):gsub("^<a", '<a data-asta-card="' .. pkey .. '" aria-haspopup="dialog"', 1)
    return el
  end
  local key = file_card(href, L.rendered_dir())
  if not key then return el end
  count("file")
  el.text = el.text:gsub('%s+title="[^"]*"', ""):gsub("^<a", '<a data-asta-card="' .. key .. '" aria-haspopup="dialog"', 1)
  return el
end

local function attach_link(el)
  local key = nil
  if el.classes:includes("quarto-xref") then
    local id = el.target:match("^#(fig%-.+)$")
    if id and figures[id] then
      key = card("g:" .. id, function() return { text = "Figure " .. figures[id].n, sections = { ADAPT.figure({ id = id }) } } end)
      count("figure")
    end
  elseif el.target:match("^https?://") then
    local n = el.target:match("^https?://autodiscovery%.allen%.ai/.-[?&]exp=(%d+)")
    local e = n and index[key_of("Experiment " .. n)]
    if e and e.test then key = mention_card(e, "Experiment " .. n) else key = external_card(el.target, pandoc.utils.stringify(el.content)) end
    el.attributes.target, el.attributes.rel = "_blank", "noopener"
    count("external")
  else
    local is_page, pkey = page_link(el.target, here_dir, pandoc.utils.stringify(el.content))
    if is_page then
      key = pkey
      if key then count("page") end
    else
      key = file_card(el.target, here_dir)
      if key then count("file") end
    end
  end
  if key then
    el.title = ""
    el.attributes["data-asta-card"] = key
    el.attributes["aria-haspopup"] = "dialog"
  end
  return el
end

local function walk_inlines(inl, done, section, quotes)
  quotes = quotes or ev_quotes(inl)
  local out, run = pandoc.List(), pandoc.List()
  local function flush()
    if #run > 0 then out:extend(link_run(run, done, section)); run = pandoc.List() end
  end
  for _, el in ipairs(inl) do
    if el.t == "Str" or el.t == "Space" or el.t == "SoftBreak" then
      run:insert(el)
    else
      flush()
      if el.t == "Span" and el.classes:includes("ev") then
        local key = ev_card(el)
        if key then el.attributes["data-asta-card"] = key; el.attributes["aria-haspopup"] = "dialog"; count("evidence") end
        out:insert(el)
      elseif el.t == "Cite" then
        local id = el.citations[1].id
        local key = citation_card(id, quotes[id])
        -- A paper of the run's paper set: a click goes to it there, not to the reference list
        -- (citeproc does not link a citation inside a link). One paper a citation, so a
        -- citation of several keeps the reference list.
        local paper = #el.citations == 1 and paper_of_cite(id)
        if key and paper then
          count("citation")
          out:insert(pandoc.Link({ el }, paper.href, "", pandoc.Attr("", { "asta-al-cite" }, card_attrs(key))))
        elseif key then
          count("citation")
          out:insert(pandoc.Span({ el }, pandoc.Attr("", { "asta-al-cite" }, card_attrs(key))))
        else
          out:insert(el)
        end
      elseif el.t == "Link" then
        out:insert(attach_link(el))
      elseif el.t == "RawInline" and el.format == "html" then
        out:insert(attach_raw(el))
      elseif CONTAINERS[el.t] then
        el.content = walk_inlines(el.content, done, section, quotes)
        out:insert(el)
      elseif el.t == "Note" then
        el.content = walk_blocks(el.content, section)
        out:insert(el)
      else
        out:insert(el)
      end
    end
  end
  flush()
  return out
end

function walk_blocks(blocks, section)
  local out = pandoc.List()
  for _, b in ipairs(blocks) do
    local t = b.t
    if t == "Header" then
      for k in pairs(section) do section[k] = nil end -- a new section: its gaps are linked afresh
    elseif t == "Para" or t == "Plain" then
      b.content = walk_inlines(b.content, {}, section)
    elseif t == "LineBlock" then
      for k, line in ipairs(b.content) do b.content[k] = walk_inlines(line, {}, section) end
    elseif t == "BlockQuote" or t == "Figure" then
      b.content = walk_blocks(b.content, section)
    elseif t == "Div" then
      -- Not the reference list, or what Quarto carries for the page's navigation and title
      -- (#quarto-navigation-envelope, #quarto-meta-markdown: .hidden).
      local skip = b.classes:includes("hidden") or b.identifier == "refs" or b.identifier:match("^quarto%-") ~= nil
      if not skip then b.content = walk_blocks(b.content, section) end
    elseif t == "BulletList" or t == "OrderedList" then
      for k, item in ipairs(b.content) do b.content[k] = walk_blocks(item, section) end
    elseif t == "DefinitionList" then
      for _, item in ipairs(b.content) do
        for k, d in ipairs(item[2]) do item[2][k] = walk_blocks(d, section) end
      end
    elseif t == "Table" then
      for _, body in ipairs(b.bodies) do
        for _, row in ipairs(body.body) do
          for _, c in ipairs(row.cells) do c.contents = walk_blocks(c.contents, section) end
        end
      end
    end
    out:insert(b)
  end
  return out
end

local function on(meta)
  local v = meta["asta-autolink"]
  if v == nil then return true end
  if type(v) == "boolean" then return v end
  return pandoc.utils.stringify(v) ~= "false"
end

return {
  {
    Pandoc = function(doc)
      if not quarto.doc.is_format("html") then return nil end
      L = L or load_lib()
      -- Every page the filter runs on joins the feed and lists its sections in the sidebar.
      L.page_extras(doc.meta)
      if not on(doc.meta) then return nil end
      here_dir = pandoc.path.directory(L.absolute(quarto.doc.input_file))
      doc:walk({
        Link = function(l)
          local n = l.target:match("^https?://autodiscovery%.allen%.ai/.-[?&]exp=(%d+)")
          if n then add("Experiment " .. n, { href = l.target, external = true, n = n }, "hosted") end
        end,
      })
      build(doc.meta)
      scan_page(doc)
      doc.blocks = walk_blocks(doc.blocks, {})
      if ncards == 0 then return doc end
      local store = {}
      for k, v in pairs(cards) do if v then store[k] = v end end
      -- The cards, once, inside the page's content (so a page appended to a flow's feed brings
      -- its own), and the scripts that draw them (asta-pages.js; tests.js for verdicts).
      doc.blocks:insert(pandoc.RawBlock("html", '<script type="application/json" class="asta-cards-data">' ..
        quarto.json.encode(store):gsub("</", "<\\/") .. "</script>"))
      quarto.doc.add_html_dependency({ name = "asta-pages", version = "0.1.0", stylesheets = { "asta-pages.css" } })
      quarto.doc.add_html_dependency({ name = "asta-pages-core", version = "0.1.0", scripts = { "asta-pages.js" } })
      quarto.doc.add_html_dependency({ name = "asta-pages-tests", version = "0.1.0", scripts = { "tests.js" } })
      local parts = {}
      for k, v in pairs(counts) do parts[#parts + 1] = k .. " " .. v end
      table.sort(parts)
      quarto.log.output("asta-autolink: " .. ncards .. " cards; " .. table.concat(parts, ", "))
      return doc
    end,
  },
}
