--[[
  runs/runs.lua — every run and its experiments, drawn into the write-up.

  An empty `::: {.runs}` div becomes one subsection per folder in runs/ that
  holds a run.md and an experiments.csv, headed by the run so it appears in
  the page's table of contents. Always in view: the prompt as
  submitted, cut at PROMPT_MAX characters with the whole of it on hover, and
  links to the hosted run and the experiments table. In a collapsed callout: every
  experiment, rises in belief first, then falls, each largest surprisal first,
  with its Agent review, Human review and Next step once any of them is filled. Nothing is
  generated or committed; the page is drawn from the run folders at each render.
  The experiments callouts take Asta's accent (allenai/design asta/tokens.json): green on
  the dark palette, teal on the light one.
]]

local stringify = pandoc.utils.stringify

local function read(path)
  local f = io.open(path, "r")
  if not f then return nil end
  local text = f:read("a")
  f:close()
  return text
end

-- The blocks under a level-2 heading, up to the next one.
local function section(blocks, name)
  local out, inside = {}, false
  for _, b in ipairs(blocks) do
    if b.t == "Header" and b.level == 2 then
      inside = stringify(b) == name
    elseif inside then
      out[#out + 1] = b
    end
  end
  return out
end

-- experiments.csv as a list of rows keyed by column name.
local function experiments(path)
  local text = read(path)
  if not text then return nil end
  text = text:gsub("^\239\187\191", "")  -- the byte-order mark the download carries
  local tbl = pandoc.read(text, "csv").blocks[1]
  local names = {}
  for i, cell in ipairs(tbl.head.rows[1].cells) do names[i] = stringify(cell.contents) end
  local rows = {}
  for _, row in ipairs(tbl.bodies[1].body) do
    local r = {}
    for i, cell in ipairs(row.cells) do r[names[i]] = stringify(cell.contents) end
    rows[#rows + 1] = r
  end
  return rows
end

local function plain(text) return { pandoc.Plain({ pandoc.Str(text) }) } end

local PROMPT_MAX = 300

-- The prompt in one line, cut at a word before PROMPT_MAX characters.
local function prompt(blocks)
  local parts = {}
  for _, b in ipairs(blocks) do parts[#parts + 1] = stringify(b) end
  local text = table.concat(parts, " ")
  if utf8.len(text) <= PROMPT_MAX then return pandoc.Para({ pandoc.Str(text) }) end
  local short = text:sub(1, utf8.offset(text, PROMPT_MAX + 1) - 1)
  short = (short:match("^(.*)%s") or short):gsub("[%s,;:]+$", "") .. "…"
  return pandoc.Para({ pandoc.Span({ pandoc.Str(short) }, { title = text }) })
end

local function run_callout(root, name)
  local dir = root .. "/runs/" .. name
  local md, exps = read(dir .. "/run.md"), experiments(dir .. "/experiments.csv")
  if not md or not exps then return nil end
  local doc = pandoc.read(md, "markdown")
  local meta = doc.meta
  -- Read from the text: YAML takes a bare N or Y, a natural label, as a boolean.
  local label = md:match("\nlabel:%s*[\"']?([^\"'\n]-)[\"']?%s*\n") or name
  local link = meta.link and stringify(meta.link) or nil
  local title = meta.title and stringify(meta.title) or (meta.name and stringify(meta.name) or name)

  table.sort(exps, function(a, b)
    local ra, rb = a["Direction"] == "Positive", b["Direction"] == "Positive"
    if ra ~= rb then return ra end
    return (tonumber(a["Surprisal"]) or 0) > (tonumber(b["Surprisal"]) or 0)
  end)
  local counts = {}
  for _, e in ipairs(exps) do counts[e["ID"]] = (counts[e["ID"]] or 0) + 1 end

  -- From the experiment to the decision, as experiments.csv reads from right to left.
  local REVIEW = { "Agent review", "Human review", "Next step" }
  local reviewed = false
  for _, e in ipairs(exps) do
    for _, col in ipairs(REVIEW) do reviewed = reviewed or (e[col] or "") ~= "" end
  end

  local rows, repeated = {}, false
  for _, e in ipairs(exps) do
    local id = label .. "-" .. e["ID"] .. (counts[e["ID"]] > 1 and "¹" or "")
    repeated = repeated or counts[e["ID"]] > 1
    local cell = link
      and { pandoc.Plain({ pandoc.Link(id, link .. "?exp=" .. e["ID"], "", { target = "_blank" }) }) }
      or plain(id)
    local row = {
      cell,
      plain(e["Hypothesis"] or ""),
      plain((e["Belief Before"] or "") .. " → " .. (e["Belief After"] or "")),
      plain(e["Surprisal"] or ""),
    }
    if reviewed then
      for _, col in ipairs(REVIEW) do row[#row + 1] = plain(e[col] or "") end
    end
    rows[#rows + 1] = row
  end
  local headers = { plain("Experiment"), plain("Hypothesis"), plain("Belief before → after"), plain("Surprisal") }
  local aligns = { pandoc.AlignDefault, pandoc.AlignDefault, pandoc.AlignDefault, pandoc.AlignRight }
  local widths = { 0, 0, 0, 0 }
  if reviewed then
    for _, col in ipairs(REVIEW) do
      headers[#headers + 1], aligns[#aligns + 1], widths[#widths + 1] = plain(col), pandoc.AlignDefault, 0
    end
  end
  local tbl = pandoc.utils.from_simple_table(pandoc.SimpleTable({}, aligns, widths, headers, rows))

  local links = {}
  if link then
    links[#links + 1] = pandoc.Link("Open in AutoDiscovery", link, "", { target = "_blank" })
    links[#links + 1] = pandoc.Str(" · ")
  end
  links[#links + 1] = pandoc.Link("experiments.csv", "runs/" .. name .. "/experiments.csv")

  local table_blocks = { tbl }
  if repeated then
    table_blocks[#table_blocks + 1] = pandoc.Para({ pandoc.Str("¹ The service gave two experiments this number; "
      .. "the link opens one of them.") })
  end
  local experiments_callout = quarto.Callout({
    type = "note",
    title = #exps .. " experiments",
    content = table_blocks,
    collapse = true,
    icon = false,
  })
  return {
    pandoc.Header(3, { pandoc.Str("Run " .. label .. ": " .. title) }, { id = "run-" .. name }),
    prompt(section(doc.blocks, "Prompt")),
    pandoc.Para(links),
    pandoc.Div({ experiments_callout }, { class = "run-experiments" }),
  }
end

local STYLE = [[
<style>
.run-experiments { --run-line: rgba(15, 203, 140, 0.4); --run-fill: rgba(15, 203, 140, 0.12); }
body.quarto-light .run-experiments { --run-line: rgba(16, 82, 87, 0.35); --run-fill: rgba(16, 82, 87, 0.08); }
.run-experiments div.callout.callout { border: 1px solid var(--run-line); border-left-width: 1px; }
.run-experiments div.callout-style-default > .callout-header { background-color: var(--run-fill); }
</style>
]]

function Div(div)
  if not div.classes:includes("runs") then return nil end
  quarto.doc.include_text("in-header", STYLE)
  local root = quarto.project.directory or "."
  local names = {}
  for _, name in ipairs(pandoc.system.list_directory(root .. "/runs")) do
    if read(root .. "/runs/" .. name .. "/run.md") then names[#names + 1] = name end
  end
  table.sort(names)
  local out = {}
  for _, name in ipairs(names) do
    for _, b in ipairs(run_callout(root, name) or {}) do out[#out + 1] = b end
  end
  -- The div gives way to its runs, so their headings reach the table of contents.
  return out
end
