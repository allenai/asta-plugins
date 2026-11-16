-- asta-pages: shortcodes that turn a run's files into page panels. A workflow page
-- (pages/<NNNN>-<workflow>.qmd) holds a title, a heading per step and these widgets, nothing
-- else: every widget links to the files on disk it was built from, so what was run is read
-- from the files, not from prose on the page.
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
-- page; literature.html when not given). `tests="<index.json>[,<index.json>...]"` adds each
-- theory's tests (an index is a list of {test_id, theory_name, ...}; a test's folder is
-- <folder of the index>/tests/<test_id>/ unless `tests_dir=` names the folder of test folders,
-- one for all indexes or one per index): a verdict column in the table and a Tests tab.
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
--
--   {{< asta-files dir=".asta/flows/0004-x/04-gap-map" >}}       a folder's files (depth=1)
--   {{< asta-doc file=".asta/flows/0004-x/04-gap-map/gaps.md" >}} a markdown file, inline
--   {{< asta-tests dir=".asta/flows/0004-x/07-tests" index=".asta/flows/0004-x/tests.json" >}}
--                                                        a table of tests, one per subfolder
--
-- These name paths relative to the project root (`dir`, `file`, `index`, `tests`, `tests_dir`
-- may be comma lists where it makes sense); an absolute path or a ".." that leaves the project
-- is refused. asta-files lists folders first, then files, with sizes (skipping __pycache__,
-- .DS_Store and names that look like credentials); past `limit=` entries (30) it gives a count
-- and a link to the folder. asta-doc renders the file's markdown with its headings moved under
-- the page's (its top heading at `level=`, 3 by default) and a header line linking the file.
-- asta-tests reads each test folder's result_summary.json (or result.json, results.json) for
-- its verdict, effect, p and animals, design.md for what it tests when no index entry says,
-- and links design, code, result, summary, figures and the folder; tests.js draws the table.
--
-- Links to files are plain relative URLs from the rendered page (in the project's output
-- directory) to the file in the project, written as raw HTML so Quarto neither copies the
-- files into the site nor warns about them: from _site/pages/0004-x.html, the project's
-- .asta/flows/0004-x/gaps.md is ../../.asta/flows/0004-x/gaps.md. Every panel carries a small
-- "Files" line linking what it was built from.

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

-- The stylesheet and asta-pages.js, which every widget script shares (a panel's start, the
-- address it owns) and which draws a flow's feed. Added before any widget script.
local function css_dep()
  quarto.doc.add_html_dependency({ name = "asta-pages", version = "0.1.0", stylesheets = { "asta-pages.css" } })
  quarto.doc.add_html_dependency({ name = "asta-pages-core", version = "0.1.0", scripts = { "asta-pages.js" } })
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

local function is_dir(path) return list_dir(path) ~= nil end

-- JSON from a file's text, or nil. Python writes NaN and Infinity, which JSON has no words for:
-- read as null. Empty text is nil without asking the decoder (which logs what it cannot read).
local function decode_json(text)
  if type(text) ~= "string" or text:match("^%s*$") then return nil end
  local clean = text:gsub("([:,%[]%s*)%-?NaN(%s*[,%]}])", "%1null%2"):gsub("([:,%[]%s*)%-?Infinity(%s*[,%]}])", "%1null%2")
  local ok, data = pcall(quarto.json.decode, clean)
  if ok then return data end
  return nil
end

local function file_size(path)
  if is_dir(path) then return nil end
  local f = io.open(path, "rb")
  if f == nil then return nil end
  local n = f:seek("end")
  f:close()
  return n
end

local function kwarg(kwargs, name)
  return pandoc.utils.stringify(kwargs[name] or ""):match("^%s*(.-)%s*$")
end

-- "G1b-T10" after "G1b-T2": names compared with their runs of digits as numbers.
local function natural_key(s)
  return (s:lower():gsub("%d+", function(d) return string.rep("0", 12 - math.min(#d, 12)) .. d end))
end
local function natural_sort(list, get)
  get = get or function(x) return x end
  table.sort(list, function(a, b) return natural_key(get(a)) < natural_key(get(b)) end)
  return list
end

-- At most n bytes of s, cut between characters, not inside one.
local function clip(s, n)
  if #s <= n then return s end
  local cut = n
  while cut > 0 and (s:byte(cut + 1) or 0) >= 0x80 and (s:byte(cut + 1) or 0) < 0xC0 do cut = cut - 1 end
  return s:sub(1, cut) .. "…"
end

-- ---- paths: the project root, where the page is rendered, and links to files on disk -------

local function slashes(p) return (p:gsub("\\", "/")) end
local function is_absolute(p) return p:match("^/") ~= nil or p:match("^%a:/") ~= nil end

-- An absolute path with "." and ".." resolved (a drive prefix such as "C:" kept).
local function normalize(p)
  p = slashes(p)
  local drive = p:match("^%a:") or ""
  local parts = {}
  for seg in p:sub(#drive + 1):gmatch("[^/]+") do
    if seg == ".." then
      if #parts > 0 then table.remove(parts) end
    elseif seg ~= "." then
      parts[#parts + 1] = seg
    end
  end
  return drive .. "/" .. table.concat(parts, "/")
end

local function absolute(p)
  p = slashes(p)
  if is_absolute(p) then return normalize(p) end
  return normalize(pandoc.system.get_working_directory() .. "/" .. p)
end

local function segments(p)
  local t = {}
  for s in p:gmatch("[^/]+") do t[#t + 1] = s end
  return t
end

-- `to` relative to the folder `from` (both absolute and normalized).
local function relative(to, from)
  local a, b = segments(from), segments(to)
  local i = 1
  while i <= #a and i <= #b and a[i] == b[i] do i = i + 1 end
  local out = {}
  for _ = i, #a do out[#out + 1] = ".." end
  for k = i, #b do out[#out + 1] = b[k] end
  return table.concat(out, "/")
end

-- The project's root folder (the page's own folder when the page is rendered on its own).
local function project_root()
  return absolute(quarto.project.directory or page_dir())
end

-- The folder the rendered page is written to: the project's output directory (_site in a
-- website), at the page's place in the project.
local function rendered_dir()
  local root, dir = project_root(), absolute(page_dir())
  local out = quarto.project.output_directory
  if out == nil or out == "" then return dir end
  out = slashes(out)
  if not is_absolute(out) then out = root .. "/" .. out end
  local inside = relative(dir, root)
  if inside:match("^%.%.") then return dir end
  return normalize(out .. "/" .. inside)
end

local function url_path(p)
  return (p:gsub("[^%w%-%._~/!$&'()*+,;=:@]", function(c) return string.format("%%%02X", c:byte()) end))
end

-- The link from the rendered page to a file (or, with a trailing slash, a folder) on disk.
local function href_to(abs, is_folder)
  local rel = relative(normalize(abs), rendered_dir())
  if rel == "" then rel = "." end
  if is_folder then rel = rel .. "/" end
  return url_path(rel)
end

-- A path as the shortcodes name it: relative to the project root (".asta/flows/...").
local function project_rel(abs) return relative(normalize(abs), project_root()) end

-- A path named in a shortcode argument, relative to the project root: its absolute form and
-- its clean relative form, or nil and why it is refused (absolute, or leaving the project).
local function project_path(rel)
  rel = slashes(rel or ""):match("^%s*(.-)%s*$")
  if rel == "" then return nil, "names no path" end
  if is_absolute(rel) or rel:match("^~") then
    return nil, rel .. " is an absolute path; name it relative to the project root"
  end
  local parts = {}
  for seg in rel:gmatch("[^/]+") do
    if seg == ".." then
      if #parts == 0 then return nil, rel .. " leaves the project; name a path inside it" end
      table.remove(parts)
    elseif seg ~= "." then
      parts[#parts + 1] = seg
    end
  end
  local clean = table.concat(parts, "/")
  return normalize(project_root() .. "/" .. clean), clean
end

local function error_box(kind, msg)
  quarto.log.warning("asta-" .. kind .. ": " .. msg)
  return pandoc.RawBlock("html", '<div class="asta-panel"><div class="ap-error">' .. html_escape(msg) .. "</div></div>")
end

-- Names a listing leaves out: caches, the Finder's files, and anything that looks like a
-- credential (keys, tokens, passwords, .env files).
local SKIP_NAMES = { ["__pycache__"] = true, [".DS_Store"] = true, [".git"] = true, [".ipynb_checkpoints"] = true }
local SECRET_WORDS = { secret = true, secrets = true, credential = true, credentials = true, password = true,
  passwords = true, passwd = true, token = true, tokens = true, apikey = true, apikeys = true, privatekey = true }
local function looks_secret(name)
  local l = name:lower()
  if l == ".env" or l:match("^%.env%.") or l:match("%.env$") or l == ".netrc" or l == ".npmrc" or l == ".pypirc"
    or l == ".git-credentials" or l:match("^id_rsa") or l:match("^id_ed25519") or l:match("^id_ecdsa")
    or l:match("%.pem$") or l:match("%.key$") or l:match("%.p12$") or l:match("%.pfx$") then
    return true
  end
  local prev
  for w in l:gmatch("[a-z0-9]+") do
    if SECRET_WORDS[w] or (prev == "api" and w == "key") or (prev == "private" and w == "key") then return true end
    prev = w
  end
  return false
end
local function skip_name(name) return SKIP_NAMES[name] or looks_secret(name) end

local function human_size(n)
  if n == nil then return "" end
  if n < 1024 then return string.format("%d B", n) end
  local units, v, i = { "KB", "MB", "GB", "TB" }, n, 0
  repeat v = v / 1024; i = i + 1 until v < 1024 or i == #units
  return (v < 10 and string.format("%.1f", v) or string.format("%.0f", v)) .. " " .. units[i]
end

-- ---- figures shown on a page: copied into the site -------------------------------------------
--
-- A link to a file opens the workspace's own file (../../.asta/...), but an image shown on the
-- page must be served from the site itself (a host may serve the output directory and nothing
-- else). Each figure a panel shows is copied, when the page renders, to
-- <output dir>/_asta/files/<its path in the project> (a folder named with a leading dot gets
-- "_" instead: "_asta/files/_asta/flows/..."), and the <img> points at the copy. Only figures
-- the page shows are copied, each at most FIGURE_MAX bytes; a larger one is not copied and the
-- page shows a link to the file instead. Without an output directory (a page rendered on its
-- own) the image points at the file.

local FIGURE_MAX = 2 * 1024 * 1024
local copied = {}

local function site_root()
  local out = quarto.project.output_directory
  if out == nil or out == "" then return nil end
  out = slashes(out)
  if not is_absolute(out) then out = project_root() .. "/" .. out end
  return normalize(out)
end

-- The src for showing the file at abs: its copy in the site, or nil and its size when it is
-- larger than FIGURE_MAX (or cannot be read).
local function figure_src(abs)
  abs = normalize(abs)
  if copied[abs] ~= nil then return copied[abs] or nil, file_size(abs) end
  local size = file_size(abs)
  if size == nil or size > FIGURE_MAX then copied[abs] = false; return nil, size end
  local site = site_root()
  local rel = project_rel(abs)
  if site == nil or rel:match("^%.%.") then copied[abs] = href_to(abs); return copied[abs], size end
  local safe = rel:gsub("[^/]+", function(seg) return (seg:gsub("^%.", "_")) end)
  local dest = site .. "/_asta/files/" .. safe
  local src = io.open(abs, "rb")
  local data = src and src:read("a")
  if src then src:close() end
  if data == nil then copied[abs] = false; return nil, size end
  pcall(pandoc.system.make_directory, pandoc.path.directory(dest), true)
  local out = io.open(dest, "wb")
  if out == nil then
    quarto.log.warning("asta-pages: cannot copy " .. rel .. " into the site")
    copied[abs] = href_to(abs)
    return copied[abs], size
  end
  out:write(data)
  out:close()
  copied[abs] = href_to(dest)
  return copied[abs], size
end

local FOLDER_ICON = '<svg class="ap-files-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M1.75 3.25h4.1l1.5 1.5h6.9v8H1.75z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>'

local function file_link(abs, is_folder, label, cls)
  return "<a" .. (cls and (' class="' .. cls .. '"') or "") .. ' href="' .. attr_escape(href_to(abs, is_folder)) ..
    '" title="' .. attr_escape(project_rel(abs) .. (is_folder and "/" or "")) .. '">' .. html_escape(label) .. "</a>"
end

-- The common folder of several absolute paths.
local function common_dir(paths)
  local common = segments(paths[1])
  for i = 2, #paths do
    local segs, k = segments(paths[i]), 1
    while k <= #common and k <= #segs and common[k] == segs[k] do k = k + 1 end
    for j = #common, k, -1 do common[j] = nil end
  end
  return "/" .. table.concat(common, "/")
end

-- The small "Files" line above a panel: the files or folders it was built from. More than
-- three files in one folder are that folder; more than three files of one name (a tests.json
-- per step) are the folder that holds them all; files of one name are told apart by folder.
local function files_bar(items)
  if #items == 0 then return "" end
  local entries, byname, order = {}, {}, {}
  local function add(e) entries[#entries + 1] = e end
  local groups, gorder = {}, {}
  for _, it in ipairs(items) do
    local d = it.folder and ("\0" .. it.abs) or pandoc.path.directory(it.abs)
    if not groups[d] then groups[d] = {}; gorder[#gorder + 1] = d end
    table.insert(groups[d], it)
  end
  for _, d in ipairs(gorder) do
    local g = groups[d]
    if #g > 3 then
      add({ html = file_link(d, true, pandoc.path.filename(d) .. "/") .. '<span class="ap-muted"> (' .. #g .. " files)</span>" })
    else
      for _, it in ipairs(g) do
        if it.folder or it.label then
          add({ html = file_link(it.abs, it.folder, it.label or (pandoc.path.filename(it.abs) .. "/")) })
        else
          local name = pandoc.path.filename(it.abs)
          if not byname[name] then byname[name] = {}; order[#order + 1] = name; add({ name = name }) end
          table.insert(byname[name], it.abs)
        end
      end
    end
  end
  local links = {}
  for _, e in ipairs(entries) do
    if e.html then
      links[#links + 1] = e.html
    else
      local list = byname[e.name]
      if #list > 3 then
        local d = common_dir(list)
        links[#links + 1] = file_link(d, true, pandoc.path.filename(d) .. "/") ..
          '<span class="ap-muted"> (' .. #list .. " × " .. html_escape(e.name) .. ")</span>"
      else
        for _, abs in ipairs(list) do
          local label = #list > 1 and (pandoc.path.filename(pandoc.path.directory(abs)) .. "/" .. e.name) or e.name
          links[#links + 1] = file_link(abs, false, label)
        end
      end
    end
  end
  return '<div class="asta-panel ap-files-bar">' .. FOLDER_ICON .. '<span class="ap-files-label">Files</span> ' ..
    table.concat(links, '<span class="ap-muted"> · </span>') .. "</div>\n"
end

-- A page-relative path (the `data` arguments) as an absolute one.
local function page_abs(rel) return absolute(pandoc.path.join({ page_dir(), rel })) end

-- ---- tests: one folder per test, read for asta-tests and asta-theories tests= ---------------

-- The first file of these in a test folder is its summary; the fields kept from it are the ones
-- the table shows (the rest, audits and per-animal detail, stays in the file it links).
local SUMMARY_FILES = { "result_summary.json", "result.json", "results.json" }
local CODE_FILES = { "test.py", "code.py" }
local SUMMARY_KEYS = { "verdict", "status", "ran", "runnable", "meets_threshold", "effect", "effect_name",
  "effect_label", "effect_units", "effect_description", "p", "p_label", "n_animals", "n_mice", "n_subjects",
  "direction" }
local INDEX_KEYS = { "theory_name", "theory_index", "kind", "dataset", "regions", "title", "name", "hypothesis",
  "question", "labels" }
local FIGURE_EXT = { png = true, jpg = true, jpeg = true, svg = true, gif = true, webp = true }

local function is_list(t) return type(t) == "table" and t[1] ~= nil end

-- A value kept for the page: strings clipped, small tables as they are, large ones dropped.
local function keep(v, n)
  if type(v) == "string" then return clip(v, n or 600) end
  if type(v) == "table" then
    local ok, enc = pcall(quarto.json.encode, v)
    if ok and #enc <= 4000 then return v end
    return nil
  end
  return v
end

local function slim_summary(d)
  local s = {}
  for _, k in ipairs(SUMMARY_KEYS) do
    if d[k] ~= nil then s[k] = keep(d[k]) end
  end
  -- A summary with several subject-level tests and no single effect (a reproduction's).
  if is_list(d.subject_level_tests) then
    local list = {}
    for i, t in ipairs(d.subject_level_tests) do
      if i > 12 then break end
      if type(t) == "table" then
        list[#list + 1] = { name = keep(t.name, 300), n_mice = keep(t.n_mice), n_animals = keep(t.n_animals),
          effect = keep(t.effect), p = keep(t.p), direction = keep(t.direction, 300) }
      end
    end
    s.subject_level_tests = list
  end
  return s
end

-- design.md: its first heading, and the paragraph under a "Hypothesis" heading if it has one.
local function design_text(text)
  local heading, hyp, fence = nil, nil, false
  local lines = {}
  for l in (text .. "\n"):gmatch("(.-)\r?\n") do lines[#lines + 1] = l end
  for i, l in ipairs(lines) do
    if l:match("^%s*```") or l:match("^%s*~~~") then fence = not fence end
    local h = not fence and l:match("^#+%s+(.-)%s*#*%s*$")
    if h then
      heading = heading or h
      if not hyp and h:lower():find("hypothes", 1, true) then
        local buf = {}
        for j = i + 1, #lines do
          local x = lines[j]
          if x:match("^#") then break end
          if x:match("^%s*$") then
            if #buf > 0 then break end
          else
            buf[#buf + 1] = x:match("^%s*(.-)%s*$")
          end
        end
        if #buf > 0 then hyp = table.concat(buf, " ") end
      end
    end
  end
  return heading and clip(heading, 300), hyp and clip(hyp, 600)
end

-- One test folder, as the page shows it: its summary's fields and links to its files.
local function test_record(dir, id)
  local names = list_dir(dir)
  if names == nil then return { id = id, missing = true } end
  local rec = { id = id, href = href_to(dir, true) }
  local has = {}
  for _, n in ipairs(names) do has[n] = true end
  local function link(n) return href_to(dir .. "/" .. n) end
  if has["design.md"] then
    rec.design = link("design.md")
    rec.heading, rec.hypothesis = design_text(read_file(dir .. "/design.md") or "")
  end
  for _, n in ipairs(CODE_FILES) do
    if has[n] then rec.code, rec.codeName = link(n), n; break end
  end
  if has["result.md"] then rec.result = link("result.md") end
  for _, n in ipairs(SUMMARY_FILES) do
    if has[n] then
      rec.summaryHref, rec.summaryName = link(n), n
      local data = decode_json(read_file(dir .. "/" .. n))
      if type(data) == "table" and not is_list(data) then rec.summary = slim_summary(data) end
      break
    end
  end
  local figs, count = {}, 0
  for _, n in ipairs(names) do
    if not skip_name(n) then
      count = count + 1
      local ext = n:lower():match("%.(%w+)$")
      if ext and FIGURE_EXT[ext] then
        -- href opens the workspace's file; src shows the copy in the site (none when too large).
        local src, size = figure_src(dir .. "/" .. n)
        figs[#figs + 1] = { name = n, href = link(n), src = src, size = (not src and size) and human_size(size) or nil }
      end
    end
  end
  if #figs > 0 then rec.figures = figs end
  rec.files = count
  return rec
end

local function slim_entry(id, e)
  local out = { test_id = id }
  if type(e) == "table" and not is_list(e) then
    for _, k in ipairs(INDEX_KEYS) do
      local v = e[k]
      if type(v) == "string" then out[k] = clip(v, 400)
      elseif type(v) == "number" or type(v) == "boolean" then out[k] = v
      elseif is_list(v) then
        local l = {}
        for i, x in ipairs(v) do
          if i > 20 then break end
          if type(x) == "string" or type(x) == "number" then l[#l + 1] = x end
        end
        out[k] = l
      end
    end
  elseif is_list(e) then
    out.labels = {}
    for _, x in ipairs(e) do if type(x) == "string" then out.labels[#out.labels + 1] = x end end
  elseif type(e) == "string" then
    out.labels = { e }
  end
  return out
end

-- A test index: a list of {test_id (or id), ...}, an object with such a list under `tests`, or
-- an object keyed by test id (each value an entry, or labels). "file.json#key" reads the index
-- under that key. Entries from an object keyed by id are `loose`: kept only where the test's
-- folder exists, since such an object may carry other fields too.
local function read_index(rel)
  local file, key = rel:match("^(.-)#(.+)$")
  file = file or rel
  local abs, clean = project_path(file)
  if not abs then return nil, "the test index " .. clean end
  local text = read_file(abs)
  if text == nil or is_dir(abs) then return nil, "cannot read the test index " .. clean end
  local data = decode_json(text)
  if type(data) ~= "table" then return nil, "the test index " .. clean .. " is not JSON" end
  if key then
    for k in key:gmatch("[^/]+") do data = type(data) == "table" and data[k] or nil end
  end
  if type(data) == "table" and is_list(data.tests) then data = data.tests end
  if type(data) ~= "table" then return nil, "the test index " .. rel .. " holds no tests" end
  local entries = {}
  if is_list(data) then
    for _, e in ipairs(data) do
      local id = type(e) == "table" and (e.test_id or e.id)
      if id ~= nil and id ~= false then entries[#entries + 1] = slim_entry(tostring(id), e) end
    end
  else
    local ids = {}
    for k in pairs(data) do ids[#ids + 1] = tostring(k) end
    natural_sort(ids)
    for _, id in ipairs(ids) do
      local e = slim_entry(id, data[id])
      e.loose = true
      entries[#entries + 1] = e
    end
  end
  return entries, nil, abs
end

-- The tests: index entries first, in their order (each with its folder under `base_for(i)`),
-- then the folders of `dirs` that no entry names, in natural order. Flat files beside the test
-- folders are `others`.
local function gather_tests(dirs, indexes)
  local folders, order, others = {}, {}, {}
  for _, d in ipairs(dirs) do
    for _, n in ipairs(list_dir(d) or {}) do
      if not skip_name(n) and n:sub(1, 1) ~= "." then
        local p = d .. "/" .. n
        if is_dir(p) then
          if not folders[n] then folders[n] = p; order[#order + 1] = n end
        else
          others[#others + 1] = { name = n, href = href_to(p), size = human_size(file_size(p)) }
        end
      end
    end
  end
  local tests, seen = {}, {}
  for _, ix in ipairs(indexes) do
    for _, e in ipairs(ix.entries) do
      local id = e.test_id
      local dir = folders[id] or (ix.base and (ix.base .. "/" .. id))
      if not seen[id] and not (e.loose and not (dir and is_dir(dir))) then
        seen[id] = true
        local rec = dir and test_record(dir, id) or { id = id, missing = true }
        e.loose = nil
        rec.index = e
        tests[#tests + 1] = rec
      end
    end
  end
  natural_sort(order)
  for _, n in ipairs(order) do
    if not seen[n] then
      seen[n] = true
      tests[#tests + 1] = test_record(folders[n], n)
    end
  end
  return tests, others
end

-- Embedded JSON: "</" cannot appear raw inside a <script> element; "<\/" is the same in JSON.
local function json_script(attrs, value)
  local text = type(value) == "string" and value or quarto.json.encode(value)
  return "<script type=\"application/json\" " .. attrs .. ">" .. text:gsub("</", "<\\/") .. "</script>"
end

local panel_count = 0
local function next_id(kind)
  panel_count = panel_count + 1
  return "asta-" .. kind .. "-" .. panel_count
end

local function tests_panel(kwargs)
  if not quarto.doc.is_format("html") then return pandoc.Null() end
  css_dep()
  quarto.doc.add_html_dependency({ name = "asta-pages-tests", version = "0.1.0", scripts = { "tests.js" } })
  local dirs, bar, errors = {}, {}, {}
  for _, rel in ipairs(split_list(kwarg(kwargs, "dir"), ",")) do
    local abs, clean = project_path(rel)
    if not abs then
      errors[#errors + 1] = "dir " .. clean
    elseif not is_dir(abs) then
      errors[#errors + 1] = "cannot read the folder " .. clean .. "; its tests appear once it exists"
    else
      dirs[#dirs + 1] = abs
      bar[#bar + 1] = { abs = abs, folder = true }
    end
  end
  local indexes = {}
  for _, rel in ipairs(split_list(kwarg(kwargs, "index"), ",")) do
    local entries, err, abs = read_index(rel)
    if entries then
      indexes[#indexes + 1] = { entries = entries }
      bar[#bar + 1] = { abs = abs }
    else
      errors[#errors + 1] = err
    end
  end
  if #dirs == 0 and #indexes == 0 then
    if #errors == 0 then errors[1] = "the shortcode names no tests folder; use dir=\".asta/flows/<run>/<step>\"." end
    return error_box("tests", "This page has no tests yet: " .. table.concat(errors, "; "))
  end
  local boxes = {}
  for _, e in ipairs(errors) do
    boxes[#boxes + 1] = error_box("tests", "Some tests are missing: " .. e).text
  end
  local tests, others = gather_tests(dirs, indexes)
  local id = next_id("tests")
  local title = kwarg(kwargs, "title")
  return pandoc.RawBlock("html", table.concat(boxes, "\n") .. (#boxes > 0 and "\n" or "") .. files_bar(bar) ..
    '<div class="asta-panel asta-tests" data-asta-data="' .. id .. '"' ..
    (title ~= "" and (' data-asta-title="' .. attr_escape(title) .. '"') or "") .. "></div>\n" ..
    json_script('class="asta-tests-data" id="' .. id .. '"', { format = "asta-pages/tests@1", tests = tests, others = others }))
end

-- asta-theories tests="a/tests.json,b/tests.json": each index's tests, their folders under
-- <folder of the index>/tests/ or tests_dir (one for all, or one per index).
local function theory_tests(kwargs, bar, errors)
  local files = split_list(kwarg(kwargs, "tests"), ",")
  if #files == 0 then return nil end
  local bases = split_list(kwarg(kwargs, "tests_dir"), ",")
  local all = {}
  for i, rel in ipairs(files) do
    local entries, err, abs = read_index(rel)
    if not entries then
      errors[#errors + 1] = err
    else
      bar[#bar + 1] = { abs = abs }
      local base = bases[i] or bases[#bases]
      local base_abs
      if base then
        local b, clean = project_path(base)
        if not b then errors[#errors + 1] = "tests_dir " .. clean else base_abs = b end
      else
        base_abs = pandoc.path.directory(abs) .. "/tests"
      end
      local tests = gather_tests({}, { { entries = entries, base = base_abs } })
      for _, t in ipairs(tests) do all[#all + 1] = t end
    end
  end
  return all
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
  -- tests.js draws a theory's tests (the Tests tab); it goes before theories.js.
  if kwarg(kwargs, "tests") ~= "" then
    css_dep()
    quarto.doc.add_html_dependency({ name = "asta-pages-tests", version = "0.1.0", scripts = { "tests.js" } })
  end
  add_deps("theories")
  local rels = split_list(pandoc.utils.stringify(kwargs["data"] or ""), ",")
  if #rels == 0 then
    local err = "the shortcode names no data file; use data=\"data/theorizer.json\"."
    quarto.log.warning("asta-theories: " .. err)
    return pandoc.RawBlock("html",
      '<div class="asta-panel"><div class="ap-error">This page has no data yet: ' .. html_escape(err) .. '</div></div>')
  end
  local errors, scripts, read, bar = {}, {}, {}, {}
  for _, rel in ipairs(rels) do
    local text, err = read_data({ data = rel })
    if err then
      quarto.log.warning("asta-theories: " .. err)
      errors[#errors + 1] = '<div class="asta-panel"><div class="ap-error">This page has no data yet: ' ..
        html_escape(err) .. '</div></div>'
    else
      read[#read + 1] = rel
      bar[#bar + 1] = { abs = page_abs(rel) }
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
  -- tests="<index>,...": each theory's tests, matched by theory name in theories.js.
  local data_bar, test_errors = bar, {}
  bar = {}
  local tests = theory_tests(kwargs, bar, test_errors)
  for _, e in ipairs(test_errors) do
    errors[#errors + 1] = error_box("theories", "Some tests are missing: " .. e).text
  end
  local tests_script = tests and ("\n" .. json_script('class="asta-theories-tests"', { format = "asta-pages/tests@1", tests = tests })) or ""
  for _, b in ipairs(bar) do data_bar[#data_bar + 1] = b end
  return pandoc.RawBlock("html", table.concat(errors, "\n") .. (#errors > 0 and "\n" or "") .. files_bar(data_bar) ..
    '<div class="asta-panel asta-theories" data-asta-source="' .. attr_escape(table.concat(read, ",")) .. '"' ..
    names_attr .. papers_attr .. '></div>\n' .. table.concat(scripts, "\n") .. tests_script)
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

-- Links to a run folder's own files: the folder, args.json and rich_outputs/ (a local run), run.md.
local function run_hrefs(dir)
  local h = { folder = href_to(dir, true) }
  if file_size(pandoc.path.join({ dir, "args.json" })) then h.args = href_to(pandoc.path.join({ dir, "args.json" })) end
  if file_size(pandoc.path.join({ dir, "run.md" })) then h.runmd = href_to(pandoc.path.join({ dir, "run.md" })) end
  if is_dir(pandoc.path.join({ dir, "rich_outputs" })) then h.richOutputs = href_to(pandoc.path.join({ dir, "rich_outputs" }), true) end
  return h
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
        slim.file, slim.href = name, href_to(pandoc.path.join({ dir, name }))
        nodes[#nodes + 1] = slim
      else
        skipped = skipped + 1
      end
    end
  end
  if skipped > 0 then
    quarto.log.warning("asta-autods: " .. skipped .. " node file(s) in " .. rel .. " could not be read")
  end
  return { kind = "nodes", source = rel, nodes = nodes, skipped = skipped, meta = local_meta(dir), hrefs = run_hrefs(dir) }
end

local function file_run(path, rel)
  local text = read_file(path)
  if text == nil then return nil end
  if not rel:lower():match("%.json$") then
    return { kind = "csv", source = rel, text = text, hrefs = { file = href_to(path) } }
  end
  -- Results JSON (`asta autodiscovery results`, the hosted Download → JSON): each experiment's
  -- figures kept in one form. A file that does not parse is passed as text, for the page to
  -- say so.
  local ok, data = pcall(quarto.json.decode, text)
  if not ok or type(data) ~= "table" then
    return { kind = "json", source = rel, text = text, hrefs = { file = href_to(path) } }
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
  return { kind = "json", source = rel, data = data, hrefs = { file = href_to(path) } }
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
  local run = { kind = "folder", source = rel, runmd = read_file(pandoc.path.join({ dir, "run.md" })), hrefs = run_hrefs(dir) }
  for _, n in ipairs(names) do
    local child, crel = pandoc.path.join({ dir, n }), rel .. "/" .. n
    if n == "results.json" or n:match("%.results%.json$") then
      run.results = file_run(child, crel)
    elseif n == "experiments.csv" then
      run.csv = read_file(child)
      run.csvSource = crel
      run.csvHref = href_to(child)
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
  local src = page_abs((rel:gsub("/$", "")))
  return pandoc.RawBlock("html", files_bar({ { abs = src, folder = is_dir(src) } }) ..
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
  return pandoc.Blocks({ head, pandoc.RawBlock("html", files_bar({ { abs = page_abs(rel) } }) ..
    '<div class="cell asta-workflow"><pre class="mermaid mermaid-js">' .. html_escape(src) .. "</pre></div>" .. sizer) })
end

-- ---- asta-literature: the paper list, with links to its papers file and search files ----------

local SEARCH_NAME = "^[%w][%w%._%-]*$"

local function literature_panel(kwargs)
  if not quarto.doc.is_format("html") then return pandoc.Null() end
  add_deps("literature")
  local text, err, rel = read_data(kwargs)
  if err then return error_box("literature", "This page has no data yet: " .. err) end
  local abs = page_abs(rel)
  local bar = { { abs = abs } }
  -- A search's own file (<name>.json), where the run kept it: the folder searches= names (from
  -- the project root), or a searches/ folder beside the papers file or beside its folder.
  local dirs, found, nfound = {}, {}, 0
  local named = kwarg(kwargs, "searches")
  if named ~= "" then
    local d, clean = project_path(named)
    if d then dirs[#dirs + 1] = d else quarto.log.warning("asta-literature: searches " .. clean) end
  end
  local here = pandoc.path.directory(abs)
  dirs[#dirs + 1] = here .. "/searches"
  dirs[#dirs + 1] = normalize(here .. "/../searches")
  local data = decode_json(text)
  if type(data) == "table" and is_list(data.searches) then
    for _, sch in ipairs(data.searches) do
      local name = type(sch) == "table" and sch.name
      if type(name) == "string" and name:match(SEARCH_NAME) then
        for _, d in ipairs(dirs) do
          local f = d .. "/" .. name .. ".json"
          if file_size(f) then
            found[name] = href_to(f)
            if nfound == 0 then bar[#bar + 1] = { abs = d, folder = true } end
            nfound = nfound + 1
            break
          end
        end
      end
    end
  end
  local safe = text:gsub("</", "<\\/")
  return pandoc.RawBlock("html", files_bar(bar) ..
    '<div class="asta-panel asta-literature" data-asta-source="' .. attr_escape(rel) .. '"' ..
    (nfound > 0 and (' data-asta-search-files="' .. attr_escape(quarto.json.encode(found)) .. '"') or "") .. "></div>\n" ..
    '<script type="application/json" id="asta-literature-data">' .. safe .. "</script>")
end

-- ---- asta-files: a folder's files, listed at render time --------------------------------------

local function files_panel(kwargs)
  if not quarto.doc.is_format("html") then return pandoc.Null() end
  css_dep()
  local rel = kwarg(kwargs, "dir")
  if rel == "" then return error_box("files", "the shortcode names no folder; use dir=\".asta/flows/<run>/<step>\".") end
  local root, clean = project_path(rel)
  if not root then return error_box("files", "dir " .. clean) end
  local names = list_dir(root)
  if names == nil then
    return error_box("files", "cannot read the folder " .. clean .. "; its files appear here once it exists.")
  end
  local depth = math.max(1, math.min(5, math.floor(tonumber(kwarg(kwargs, "depth")) or 1)))
  local budget = math.max(1, math.floor(tonumber(kwarg(kwargs, "limit")) or 30))
  local nfiles, nfolders = 0, 0

  local function visible(list)
    local out = {}
    for _, n in ipairs(list or {}) do if not skip_name(n) then out[#out + 1] = n end end
    return out
  end

  local function listing(dir, list, level)
    local folders, files = {}, {}
    for _, n in ipairs(visible(list)) do
      local p = dir .. "/" .. n
      local sub = list_dir(p)
      if sub then folders[#folders + 1] = { n = n, p = p, sub = sub } else files[#files + 1] = { n = n, p = p } end
    end
    if level == 1 then nfiles, nfolders = #files, #folders end
    natural_sort(folders, function(x) return x.n end)
    natural_sort(files, function(x) return x.n end)
    local items, shown = {}, 0
    for _, group in ipairs({ folders, files }) do
      for _, e in ipairs(group) do
        if budget <= 0 then break end
        budget = budget - 1
        shown = shown + 1
        if e.sub then
          local kids = visible(e.sub)
          items[#items + 1] = '<li class="ap-fl-dir">' .. file_link(e.p, true, e.n .. "/") ..
            '<span class="ap-fl-meta">' .. #kids .. (#kids == 1 and " item" or " items") .. "</span>" ..
            ((level < depth and #kids > 0) and listing(e.p, e.sub, level + 1) or "") .. "</li>"
        else
          items[#items + 1] = "<li>" .. file_link(e.p, false, e.n) ..
            '<span class="ap-fl-meta">' .. human_size(file_size(e.p)) .. "</span></li>"
        end
      end
    end
    local more = #folders + #files - shown
    if more > 0 then
      items[#items + 1] = '<li class="ap-fl-more">' .. more .. " more · " .. file_link(dir, true, "open the folder") .. "</li>"
    end
    if #items == 0 then items[1] = '<li class="ap-fl-more">This folder is empty.</li>' end
    return '<ul class="ap-fl">' .. table.concat(items) .. "</ul>"
  end

  local body = listing(root, names, 1)
  local counts = {}
  if nfolders > 0 then counts[#counts + 1] = nfolders .. (nfolders == 1 and " folder" or " folders") end
  counts[#counts + 1] = nfiles .. (nfiles == 1 and " file" or " files")
  return pandoc.RawBlock("html", '<div class="asta-panel asta-files"><div class="ap-files-bar">' .. FOLDER_ICON ..
    '<span class="ap-files-label">Files</span> ' .. file_link(root, true, pandoc.path.filename(root) .. "/") ..
    '<span class="ap-muted"> · ' .. table.concat(counts, ", ") .. "</span></div>" .. body .. "</div>")
end

-- ---- asta-doc: a markdown file from disk, inline ---------------------------------------------

local DOC_ICON = '<svg class="ap-files-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 1.75h6l3 3v9.5h-9z M9.5 1.75v3h3" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>'

-- The id an entry of a document starts with: "G1 …", "G1. …", "G1: …", "[G1, …] …" -> "G1"
-- (a capital, digits, and an optional letter: "G1b").
local function entry_id(text)
  return text:match("^%s*%[?(%u%d+%l?)[%]%s,:%.;)]") or text:match("^%s*%[?(%u%d+%l?)$")
end

local function url_decode(s)
  return (s:gsub("%%(%x%x)", function(h) return string.char(tonumber(h, 16)) end))
end

local function doc_panel(kwargs)
  if not quarto.doc.is_format("html") then return pandoc.Null() end
  css_dep()
  local rel = kwarg(kwargs, "file")
  if rel == "" then return error_box("doc", "the shortcode names no file; use file=\".asta/flows/<run>/<step>/<name>.md\".") end
  local abs, clean = project_path(rel)
  if not abs then return error_box("doc", "file " .. clean) end
  local text = not is_dir(abs) and read_file(abs) or nil
  if text == nil then return error_box("doc", "cannot read " .. clean .. "; it appears here once the step writes it.") end
  -- Pandoc's markdown without citations (an "@" in a run's notes is not a reference to look up).
  local ok, doc = pcall(pandoc.read, text, "markdown-citations")
  if not ok then return error_box("doc", "cannot read " .. clean .. " as markdown") end
  local level = math.max(1, math.min(6, math.floor(tonumber(kwarg(kwargs, "level")) or 3)))
  local top = 7
  doc.blocks:walk({ Header = function(h) if h.level < top then top = h.level end end })
  local shift = top == 7 and 0 or level - top
  local base = pandoc.path.directory(abs)
  local slug = clean:lower():gsub("[^%w]+", "-")
  -- Links and images that name files beside the document point at those files from the
  -- rendered page; they are written as raw HTML so Quarto does not copy them into the site.
  local function target(t)
    if t == "" or t:match("^#") or t:match("^%a[%w+.-]*:") or t:match("^//") then return nil end
    local path, rest = t:match("^([^#?]*)(.*)$")
    if path == "" or path:match("^/") then return nil end
    return href_to(normalize(base .. "/" .. url_decode(path)), path:match("/$") ~= nil) .. rest
  end
  -- A list item that starts with an id ("G1. …", "[G1, untested link] …") is an entry others
  -- link to: it gets the anchor doc-<file>-<id> (autolink.lua's gap cards link there).
  local function entry_anchors(list)
    for _, item in ipairs(list.content) do
      local first = item[1]
      local id = first and (first.t == "Plain" or first.t == "Para") and entry_id(pandoc.utils.stringify(first))
      if id then first.content:insert(1, pandoc.Span({}, pandoc.Attr("doc-" .. slug .. "-" .. id:lower()))) end
    end
    return list
  end
  local blocks = doc.blocks:walk({
    BulletList = entry_anchors,
    OrderedList = entry_anchors,
    Header = function(h)
      h.level = math.max(1, math.min(6, h.level + shift))
      if h.identifier ~= "" then h.identifier = "doc-" .. slug .. "-" .. h.identifier end
      h.classes:insert("unlisted")
      h.classes:insert("unnumbered")
      return h
    end,
    Link = function(l)
      local href = target(l.target)
      if not href then return nil end
      local out = pandoc.Inlines({ pandoc.RawInline("html", '<a href="' .. attr_escape(href) .. '"' ..
        (l.title ~= "" and (' title="' .. attr_escape(l.title) .. '"') or "") .. ">") })
      out:extend(l.content)
      out:insert(pandoc.RawInline("html", "</a>"))
      return out
    end,
    Image = function(img)
      local href = target(img.src)
      if not href then return nil end
      -- Shown from its copy in the site; a figure too large to copy is a link to the file.
      local path = img.src:match("^([^#?]*)")
      local file = normalize(base .. "/" .. url_decode(path))
      local alt = pandoc.utils.stringify(img.caption)
      local src, size = figure_src(file)
      if not src then
        return pandoc.RawInline("html", '<a class="ap-doc-img-link" href="' .. attr_escape(href) .. '">' ..
          html_escape(pandoc.path.filename(file)) .. "</a>" ..
          (size and ('<span class="ap-muted"> (' .. human_size(size) .. ", too large to show here)</span>") or ""))
      end
      return pandoc.RawInline("html", '<img class="ap-doc-img" src="' .. attr_escape(src) .. '" alt="' ..
        attr_escape(alt) .. '" loading="lazy">')
    end,
  })
  local head = '<div class="asta-panel ap-files-bar ap-doc-head">' .. DOC_ICON .. file_link(abs, false, pandoc.path.filename(abs)) ..
    '<span class="ap-muted"> · ' .. human_size(file_size(abs)) .. " · </span>" ..
    file_link(base, true, "its folder") .. "</div>"
  return pandoc.Blocks({ pandoc.RawBlock("html", head), pandoc.Div(blocks, pandoc.Attr("", { "asta-doc" })) })
end

-- ---- the feed, and each page's sections in the sidebar -----------------------------------
--
-- Every page the asta-pages filter or one of its shortcodes runs on carries two small JSON blocks
-- for asta-pages.js:
--   script#asta-flow      where the site's root is. The feed's pages are the sidebar's links into
--                         the site, in the sidebar's order: in a workspace the front page, then
--                         the workflow pages (pages/<NNNN>-<workflow>.qmd, listed flat with
--                         `auto: "pages/*.qmd"`, so by file name: run order). The page the reader
--                         is on loads the pages after it, below it, as the reader reaches its end.
--   script#asta-sections  each page's sections: its level-2 headings and the ids Quarto gives
--                         them, keyed by the page's place in the site, for the pages the project
--                         renders. Listed under each page's sidebar link. Off with
--                         `asta-pages: {sidebar-sections: false}` in _quarto.yml.

local function meta_text(v)
  if v == nil then return "" end
  return pandoc.utils.stringify(v):match("^%s*(.-)%s*$")
end

-- A page's front matter as Pandoc metadata (an empty table when it has none).
local function front_matter(path)
  local text = read_file(path)
  if not text then return nil end
  text = text:gsub("^\239\187\191", ""):gsub("\r\n", "\n")
  local yaml = text:match("^%-%-%-[ \t]*\n(.-\n)%-%-%-[ \t]*\n") or text:match("^%-%-%-[ \t]*\n(.-\n)%-%-%-[ \t]*$")
  if not yaml then return {} end
  local ok, doc = pcall(pandoc.read, "---\n" .. yaml .. "---\n", "markdown")
  if not ok then return {} end
  return doc.meta
end

-- Where a page source renders: <output dir>/<its place in the project>.html.
local function rendered_file(src)
  local root = project_root()
  local out = quarto.project.output_directory
  local inside = relative(src, root):gsub("%.[^./]+$", "") .. ".html"
  if out == nil or out == "" then return normalize(root .. "/" .. inside) end
  out = slashes(out)
  if not is_absolute(out) then out = root .. "/" .. out end
  return normalize(out .. "/" .. inside)
end

-- The workflow pages: pages/*.qmd, by file name (run order).
local function workflow_pages()
  local root = project_path("pages")
  local out = {}
  for _, name in ipairs(root and list_dir(root) or {}) do
    if name:match("%.qmd$") and not name:match("^[_.]") then out[#out + 1] = normalize(root .. "/" .. name) end
  end
  return out
end

-- The project's render list (project.render in _quarto.yml), its globs expanded (a `*` in the
-- last part of a path); without one, the .qmd files at the root and in pages/.
local function render_list()
  local root = project_root()
  local text = read_file(root .. "/_quarto.yml") or read_file(root .. "/_quarto.yaml")
  local items = {}
  if text then
    local ok, doc = pcall(pandoc.read, "---\n" .. text:gsub("\r\n", "\n") .. "\n---\n", "markdown")
    local render = ok and doc.meta.project and doc.meta.project.render
    if type(render) == "table" then
      for _, v in ipairs(render) do items[#items + 1] = pandoc.utils.stringify(v) end
    end
  end
  if #items == 0 then items = { "*.qmd", "pages/*.qmd" } end
  local out, seen = {}, {}
  local function add(p)
    p = normalize(p)
    if not seen[p] and file_size(p) then seen[p] = true; out[#out + 1] = p end
  end
  for _, item in ipairs(items) do
    local dir, name = item:match("^(.*)/([^/]*)$")
    if not dir then dir, name = "", item end
    if item:sub(1, 1) ~= "!" and not dir:find("[*?]") then
      local base = dir == "" and root or (root .. "/" .. dir)
      if name:find("[*?]") then
        local pat = "^" .. name:gsub("[%^%$%(%)%%%.%[%]%+%-]", "%%%0"):gsub("%*", "[^/]*"):gsub("%?", "[^/]") .. "$"
        local names = list_dir(base) or {}
        table.sort(names)
        for _, n in ipairs(names) do
          if n:match(pat) and not n:match("^[_.]") and n:match("%.q?md$") then add(base .. "/" .. n) end
        end
      else
        add(base .. "/" .. name)
      end
    end
  end
  return out
end

-- A page's sections: its level-2 headings ({id, title}), read from its source with the ids
-- Quarto gives them (an explicit {#id}, else Pandoc's identifier for the heading's text), and
-- the "Workflow" heading asta-workflow draws when the page's diagram is there. Headings marked
-- .unlisted are left out, as Quarto leaves them out of "On this page". nil for a slide deck.
local function page_sections(path)
  local text = read_file(path)
  if not text then return nil end
  local fm = front_matter(path) or {}
  local fmt = fm.format
  if type(fmt) == "table" and fmt.revealjs ~= nil and fmt.html == nil then return nil end
  if fmt ~= nil and pandoc.utils.stringify(fmt):match("^revealjs") then return nil end
  local dir = pandoc.path.directory(path)
  text = ("\n" .. text:gsub("^\239\187\191", ""):gsub("\r\n", "\n")):gsub("\n[ \t]*{{<%s*asta%-workflow(.-)>}}", function(args)
    local file = args:match('file%s*=%s*"([^"]*)"') or args:match("file%s*=%s*([^%s\"]+)") or "workflow.mmd"
    local title = args:match('title%s*=%s*"([^"]*)"') or "Workflow"
    local src = read_file(normalize(dir .. "/" .. file))
    if not src or src:match("^%s*$") then return "\n" end
    return "\n\n## " .. title .. " {#workflow}\n\n"
  end)
  local ok, doc = pcall(pandoc.read, text, "markdown")
  if not ok then return {} end
  local out = {}
  doc.blocks:walk({
    Header = function(h)
      if h.level == 2 and h.identifier ~= "" and not h.classes:includes("unlisted") then
        out[#out + 1] = { id = h.identifier, title = pandoc.utils.stringify(h.content) }
      end
    end,
  })
  return out
end

local function option(meta, name)
  local o = meta and meta["asta-pages"]
  if type(o) ~= "table" then return nil end
  local v = o[name]
  if v == nil or type(v) == "boolean" then return v end
  local s = pandoc.utils.stringify(v)
  return s ~= "false" and s ~= "no"
end

-- The feed's and the sidebar's data, once per page (the shortcodes and the filter each load
-- this file; the page renders in one Lua state, so the mark is kept in package.loaded).
local function page_extras(meta)
  local state = package.loaded["asta-pages/page"] or {}
  package.loaded["asta-pages/page"] = state
  if state.done then return end
  state.done = true
  if not quarto.doc.is_format("html") or quarto.doc.is_format("revealjs") then return end
  local site = site_root() or project_root()
  local rel = relative(site, rendered_dir())
  local to_root = rel == "" and "./" or (url_path(rel) .. "/")
  css_dep()
  quarto.doc.include_text("after-body", json_script('id="asta-flow"', { format = "asta-pages/flow@3", site = to_root }))
  if option(meta, "sidebar-sections") == false then return end
  local pages, any = {}, false
  for _, src in ipairs(render_list()) do
    local list = page_sections(src)
    if list and #list > 0 then
      pages[url_path(relative(rendered_file(src), site))] = list
      any = true
    end
  end
  if any then
    quarto.doc.include_text("after-body", json_script('id="asta-sections"',
      { format = "asta-pages/sections@1", site = to_root, pages = pages }))
  end
end

-- ---- a figure's provenance: figure.json --------------------------------------------------
--
-- A figure's folder may carry a figure.json naming what the figure was made from:
--   {"id": "<fig-id>", "script": "make_figure.py", "inputs": ["<project path>", …], "audit": "audit.json"}
-- `script` and `audit` are relative to that folder, `inputs` to the project root; an input
-- outside the workspace (an absolute path or a URL, e.g. a mounted dataset) is named but not linked. The folder is
-- the image's own, a step folder named for the figure (.asta/flows/*/*/<fig-id>/), or any step
-- folder whose figure.json gives that id. Returns nil without one; files it names that do not
-- exist are reported with a render warning (unless quiet) and come back as missing, never as
-- links.

local function figure_provenance(id, image_abs, quiet)
  local tries = {}
  if image_abs then tries[#tries + 1] = pandoc.path.directory(image_abs) .. "/figure.json" end
  local flows = project_path(".asta/flows")
  local steps = {}
  for _, flow in ipairs(flows and list_dir(flows) or {}) do
    for _, step in ipairs(list_dir(flows .. "/" .. flow) or {}) do steps[#steps + 1] = flows .. "/" .. flow .. "/" .. step end
  end
  for _, st in ipairs(steps) do tries[#tries + 1] = st .. "/" .. id .. "/figure.json" end
  local file, data = nil, nil
  for _, f in ipairs(tries) do
    local d = decode_json(read_file(f))
    if type(d) == "table" and not is_list(d) and (d.id == nil or d.id == id) then file, data = f, d; break end
  end
  if not data then
    for _, st in ipairs(steps) do
      for _, sub in ipairs(list_dir(st) or {}) do
        local d = decode_json(read_file(st .. "/" .. sub .. "/figure.json"))
        if type(d) == "table" and d.id == id then file, data = st .. "/" .. sub .. "/figure.json", d; break end
      end
      if data then break end
    end
  end
  if not data then return nil end
  local dir = pandoc.path.directory(file)
  local function one(abs, label)
    if file_size(abs) == nil then
      if not quiet then quarto.log.warning("asta-pages: figure " .. id .. ": " .. label .. " " .. project_rel(abs) .. " not found") end
      return { name = pandoc.path.filename(abs), rel = project_rel(abs), missing = true }
    end
    return { name = pandoc.path.filename(abs), rel = project_rel(abs), href = href_to(abs) }
  end
  local out = { id = id, dir = dir, folder = href_to(dir, true), inputs = {} }
  if type(data.script) == "string" and data.script ~= "" then out.script = one(normalize(dir .. "/" .. data.script), "script") end
  for _, rel in ipairs(is_list(data.inputs) and data.inputs or {}) do
    if type(rel) == "string" then
      local abs, clean = project_path(rel)
      if abs then out.inputs[#out.inputs + 1] = one(abs, "input")
      elseif rel:match("^/") or rel:match("^%a[%w+.-]*://") then
        -- Data outside the workspace (a mounted dataset, an archive URL): named, never linked.
        out.inputs[#out.inputs + 1] = { name = pandoc.path.filename((rel:gsub("/$", ""))), rel = rel, outside = true }
      elseif not quiet then quarto.log.warning("asta-pages: figure " .. id .. ": input " .. clean) end
    end
  end
  if type(data.audit) == "string" and data.audit ~= "" then
    out.audit = one(normalize(dir .. "/" .. data.audit), "audit")
    local a = not out.audit.missing and decode_json(read_file(normalize(dir .. "/" .. data.audit)))
    if type(a) == "table" and type(a.verdict) == "string" then out.verdict = a.verdict end
  end
  return out
end

-- ---- asta-datasets: the workspace's datasets, from .asta/datasets.json -----------------------
--
-- [{"id", "name", "released_by", "used_for", "links": [{"label", "url"}]}] -> a table: Dataset,
-- Released by, Used for, Links. It is an ordinary table of the page, so the page's link cards
-- read it like the rest of the text (a dataset's links open its card; ids in "Used for" link).

local function datasets_panel(kwargs)
  local rel = kwarg(kwargs, "file")
  if rel == "" then rel = ".asta/datasets.json" end
  local abs, clean = project_path(rel)
  if not abs then return error_box("datasets", "file " .. clean) end
  local data = decode_json(read_file(abs))
  if not is_list(data) then
    return error_box("datasets", "cannot read " .. clean .. " as a list of datasets; a workflow step writes it.")
  end
  local function cell(v) return (tostring(v or ""):gsub("[\r\n]+", " "):gsub("|", "\\|")) end
  local rows = { "| Dataset | Released by | Used for | Links |", "|---|---|---|---|" }
  for _, d in ipairs(data) do
    if type(d) == "table" then
      local links = {}
      for _, l in ipairs(is_list(d.links) and d.links or {}) do
        if type(l) == "table" and type(l.url) == "string" then
          links[#links + 1] = "[" .. cell(l.label or l.url):gsub("[%[%]]", "\\%0") .. "](" .. l.url .. ")"
        end
      end
      rows[#rows + 1] = "| " .. cell(d.name or d.id) .. " | " .. cell(d.released_by) .. " | " .. cell(d.used_for) ..
        " | " .. table.concat(links, " · ") .. " |"
    end
  end
  css_dep()
  local doc = pandoc.read(table.concat(rows, "\n") .. "\n", "markdown")
  local blocks = pandoc.Blocks({ pandoc.RawBlock("html", files_bar({ { abs = abs } })) })
  blocks:extend(doc.blocks)
  return blocks
end

-- The helpers autolink.lua and provenance.lua (the asta-pages filters) share with the
-- shortcodes: they load this file and read them from here.
ASTA_PAGES_LIB = {
  project_root = project_root, project_path = project_path, absolute = absolute, normalize = normalize,
  relative = relative, rendered_dir = rendered_dir, rendered_file = rendered_file, url_path = url_path,
  list_dir = list_dir, is_dir = is_dir, read_file = read_file, decode_json = decode_json,
  split_list = split_list, natural_sort = natural_sort, is_list = is_list, skip_name = skip_name,
  read_index = read_index, is_node_file = is_node_file, has_nodes = has_nodes, autods_runs = autods_runs,
  front_matter = front_matter, workflow_pages = workflow_pages, meta_text = meta_text, page_extras = page_extras,
  slim_summary = slim_summary, summary_files = SUMMARY_FILES, url_decode = url_decode, file_size = file_size,
  human_size = human_size, site_root = site_root, entry_id = entry_id, href_to = href_to,
  html_escape = html_escape, attr_escape = attr_escape, figure_provenance = figure_provenance,
}

return {
  ["asta-workflow"] = function(args, kwargs, meta)
    page_extras(meta)
    return workflow(kwargs)
  end,
  ["asta-theories"] = function(args, kwargs, meta)
    page_extras(meta)
    return theories_panel(kwargs)
  end,
  ["asta-literature"] = function(args, kwargs, meta)
    page_extras(meta)
    return literature_panel(kwargs)
  end,
  ["asta-autods"] = function(args, kwargs, meta)
    page_extras(meta)
    return autods(kwargs)
  end,
  ["asta-files"] = function(args, kwargs, meta)
    page_extras(meta)
    return files_panel(kwargs)
  end,
  ["asta-doc"] = function(args, kwargs, meta)
    page_extras(meta)
    return doc_panel(kwargs)
  end,
  ["asta-datasets"] = function(args, kwargs, meta)
    page_extras(meta)
    return datasets_panel(kwargs)
  end,
  ["asta-tests"] = function(args, kwargs, meta)
    page_extras(meta)
    return tests_panel(kwargs)
  end,
}
