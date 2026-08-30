--[[
  evidence/snippet.lua — hover-viewable supporting quotes for claims.

  Every factual claim in the prose can carry the evidence that backs it, so a
  reader can check the source without leaving the text and a reviewer can see
  the backing quote directly in the "what-changed" diff.

  A claim is a VERBATIM QUOTE plus a REFERENCE (with an optional locator). The
  quote text lives in an EXTERNAL keyed store (evidence.yml, merged into
  document metadata under `evidence:` via `metadata-files` in _quarto.yml). A
  claim in the .qmd then carries only a short key, which keeps the prose
  readable and puts the quotes in one structured file edited on its own:

      NatureBench has [90]{.ev key="naturebench-count"} tasks.

  with, in evidence.yml:

      evidence:
        naturebench-count:
          quote: "a cross-discipline benchmark of 90 tasks ..."
          cite: naturebench2026
          locator: abstract

  The same attributes may still be given INLINE for a one-off claim that does
  not warrant a store entry (or to override a stored field):

      [90 tasks]{.ev quote="..." cite="naturebench2026" locator="p. 4"}

  Fields (from the store entry and/or inline):
    key      look the evidence up by this key in the `evidence:` metadata store
    quote    the VERBATIM quotation from the source (required); rendered in
             “curly quotes” + italic so it reads as exact wording, not a gloss
    cite     a bibliography key from references.bib; rendered as a real citation
             in the SAME author–year format the body text uses
    source   free-text citation for a source with no bib key (fallback for cite)
    url      link for a `source` that has no bib key
    locator  a NATIVE Pandoc/citeproc citation locator appended to the citation
             — e.g. "p. 4", "pp. 4-6", "sec. 3.2", "chap. 2", "abstract". This
             is Pandoc's own locator syntax (the part after the comma in
             `[@key, p. 4]`), so citeproc formats it in the site's citation
             style; we do NOT re-invent a locator format. See README.
  Inline attributes take precedence over the stored entry field by field.

  PROVENANCE — how the quote was obtained (an Asta snippet search vs. read from
  the paper vs. a produced artifact) is RETAINED per entry under `provenance:`
  and reviewable in the evidence.yml diff, but is NOT shown by default in the
  popover: the primary view is just the quote and its reference. Provenance sits
  behind a small, collapsed “Source details” disclosure so it is available on
  demand without overwhelming the read. The schema is deliberately small and
  open — `method` is a free string and the few optional fields render only when
  present, so a new derived-evidence kind (e.g. a Theorizer report cited by its
  asta:// URI) needs no code change:
    provenance:
      method     how it was obtained, free text — e.g. "asta-snippet-search",
                 "paper", "theorizer" (a known value gets a friendlier label)
      query      the search query that surfaced the quote (for search methods)
      corpus_id  S2 corpusId of the source paper (rendered as an S2 link)
      url        canonical link to the source or a produced artifact/report URI
      retrieved  ISO date the evidence was obtained
      note       free text

  The evidence is emitted as a real, hidden child span (`.ev-pop`) of the claim
  — not stuffed into a data-* attribute — so the quote and citation render as
  genuine markup on both the full site AND the workspace "what-changed" diff
  page, and a pure-CSS `:hover`/`:focus-within` reveal shows it (no JavaScript
  required). Because the popover is a DOM descendant of the claim, hovering it
  keeps the claim's `:hover` alive, so the tooltip never drops out from a gap
  between the claim and the box. For non-HTML output the class and attributes
  are simply ignored, so the claim text still renders normally.
]]

-- The keyed evidence store, populated from document metadata in Pandoc(doc)
-- before any span is transformed.
local store = {}

local FIELDS = { 'quote', 'cite', 'source', 'url', 'locator' }
local PROV_FIELDS = { 'method', 'query', 'corpus_id', 'url', 'retrieved', 'note' }

-- Parse an entry's nested `provenance:` map into a plain lua table. Returns nil
-- when there is nothing to show, so callers can treat provenance as optional.
local function load_prov(pv)
  if pv == nil then return nil end
  local rec = {}
  for _, f in ipairs(PROV_FIELDS) do
    if pv[f] ~= nil then
      local s = pandoc.utils.stringify(pv[f])
      if s ~= '' then rec[f] = s end
    end
  end
  if next(rec) == nil then return nil end
  return rec
end

-- Read `evidence:` out of the document metadata into a plain lua table
-- { key = { quote = "...", cite = "...", ... } }. Metadata values arrive as
-- pandoc inline lists / MetaString, so each field is stringified to plain text.
local function load_store(meta)
  local ev = meta and meta.evidence
  if ev == nil then return end
  for key, entry in pairs(ev) do
    local rec = {}
    for _, f in ipairs(FIELDS) do
      if entry[f] ~= nil then
        local s = pandoc.utils.stringify(entry[f])
        if s ~= '' then rec[f] = s end
      end
    end
    rec.provenance = load_prov(entry.provenance)
    store[key] = rec
  end
end

-- Friendly labels for the known provenance methods. An unknown method renders
-- its own string verbatim, so a new derivation kind needs no code change here.
local METHOD_LABELS = {
  ['paper'] = 'read from paper',
  ['asta-snippet-search'] = 'Asta snippet search',
  ['snippet-search'] = 'snippet search',
  ['semantic-scholar'] = 'Semantic Scholar snippet search',
  ['find-literature'] = 'Asta Paper Finder',
  ['theorizer'] = 'Theorizer report',
  ['literature-report'] = 'literature report',
  ['manual'] = 'author-entered',
}

local function html_escape(s)
  return (s:gsub('[&<>"]', {
    ['&'] = '&amp;', ['<'] = '&lt;', ['>'] = '&gt;', ['"'] = '&quot;',
  }))
end

-- Build the collapsed "Source details" disclosure as one raw-HTML inline.
--
-- It MUST be phrasing (inline) content only — plain <span>s, no <details>/<div>
-- or any other flow element. The whole popover lives inside the claim's inline
-- <span>, and the workspace "what-changed" diff wraps an inserted claim in
-- <ins>. A block element nested in that inline run forces the diff to emit a
-- </ins> mid-nesting, which the HTML parser resolves by closing the popover's
-- open <span>s too — ejecting a <details> out of the hidden popover so it
-- renders as stray visible text (and strands fragments the folder mis-collapses)
-- inside table cells. Keeping the disclosure inline keeps the popover a single
-- valid phrasing subtree that survives the diff intact. The disclosure is shown
-- on demand with pure CSS (`.ev-src:hover`/`:focus-within`), no JavaScript, and
-- every tag/attribute here is on the what-changed allowlist. Returns nil when
-- there is no provenance to show.
local function build_prov_details(prov)
  if prov == nil then return nil end
  local method = prov.method and (METHOD_LABELS[prov.method] or prov.method) or nil
  local summary = method and ('Source details — ' .. method) or 'Source details'

  local rows = {}
  if prov.query then
    rows[#rows + 1] = 'query: <em>“' .. html_escape(prov.query) .. '”</em>'
  end
  if prov.corpus_id then
    rows[#rows + 1] = '<a href="https://www.semanticscholar.org/paper/CorpusID:'
      .. html_escape(prov.corpus_id) .. '">S2 #' .. html_escape(prov.corpus_id) .. '</a>'
  end
  if prov.url then
    rows[#rows + 1] = '<a href="' .. html_escape(prov.url) .. '">source ↗</a>'
  end
  if prov.retrieved then rows[#rows + 1] = 'retrieved ' .. html_escape(prov.retrieved) end
  if prov.note then rows[#rows + 1] = html_escape(prov.note) end

  local body = ''
  if #rows > 0 then
    body = '<span class="ev-prov-body">' .. table.concat(rows, ' · ') .. '</span>'
  end
  -- An all-inline disclosure: a focusable label plus a body revealed by CSS on
  -- hover/focus. tabindex makes it keyboard-reachable so `:focus-within` opens
  -- it without any script.
  local htmlstr = '<span class="ev-src"><span class="ev-src-label" tabindex="0">'
    .. html_escape(summary) .. '</span>' .. body .. '</span>'
  return pandoc.RawInline('html', htmlstr)
end

local function attr(el, name)
  local v = el.attributes[name]
  if v == nil or v == '' then return nil end
  return v
end

-- Resolve a field from the inline attribute first, then the stored entry.
local function resolve(el, entry, name)
  local v = attr(el, name)
  if v ~= nil then return v end
  if entry ~= nil then return entry[name] end
  return nil
end

local function transform(el)
  if not el.classes:includes('ev') then return nil end

  local key = attr(el, 'key')
  local entry = key and store[key] or nil
  if key and entry == nil then
    io.stderr:write('[evidence] .ev span references unknown key "' .. key
      .. '": "' .. pandoc.utils.stringify(el.content) .. '"\n')
  end

  local quote = resolve(el, entry, 'quote')
  if quote == nil then
    -- A claim marked `.ev` with no quote is almost always a mistake; make it
    -- visible during authoring rather than silently dropping the evidence.
    io.stderr:write('[evidence] .ev span with no quote= (or resolvable key): "'
      .. pandoc.utils.stringify(el.content) .. '"\n')
    return nil
  end

  local cite = resolve(el, entry, 'cite')
  local source = resolve(el, entry, 'source')
  local url = resolve(el, entry, 'url')
  local locator = resolve(el, entry, 'locator')
  local prov = entry and entry.provenance or nil

  -- Drop the authoring attributes so they don't render as stray HTML.
  for _, k in ipairs({ 'key', 'quote', 'cite', 'source', 'url', 'locator' }) do
    el.attributes[k] = nil
  end

  -- The verbatim quote: real typographic quotes + italics so it reads as exact
  -- wording.
  local textSpan = pandoc.Span(
    { pandoc.Quoted(pandoc.DoubleQuote, { pandoc.Emph({ pandoc.Str(quote) }) }) },
    pandoc.Attr('', { 'ev-pop-text', 'ev-quote' }))

  -- The reference line. A `cite` key becomes a real Cite so citeproc renders it
  -- in exactly the author–year format (and #ref- link) the body text uses; a
  -- NATIVE citeproc locator (e.g. "p. 4", "sec. 3.2") is carried in the
  -- citation suffix so citeproc — not us — formats it in the site's style. A
  -- free-text `source` (optionally linked by `url`) is the fallback.
  local srcInlines = nil
  if cite then
    local citation = pandoc.Citation(cite, 'NormalCitation')
    if locator then citation.suffix = { pandoc.Str(', '), pandoc.Str(locator) } end
    local citeEl = pandoc.Cite({ pandoc.Str('[' .. cite .. ']') }, { citation })
    srcInlines = { pandoc.Str('— '), citeEl }
  elseif source then
    local label = pandoc.Str(source)
    local srcNode = url and pandoc.Link({ label }, url) or label
    srcInlines = { pandoc.Str('— '), srcNode }
    if locator then srcInlines[#srcInlines + 1] = pandoc.Str(', ' .. locator) end
  elseif url then
    srcInlines = { pandoc.Str('— '), pandoc.Link({ pandoc.Str(url) }, url) }
  end

  local cardChildren = { textSpan }
  if srcInlines then
    cardChildren[#cardChildren + 1] = pandoc.Span(srcInlines, pandoc.Attr('', { 'ev-pop-src' }))
  end
  -- Provenance, retained but collapsed (not shown by default).
  local provDetails = build_prov_details(prov)
  if provDetails then cardChildren[#cardChildren + 1] = provDetails end

  local card = pandoc.Span(cardChildren, pandoc.Attr('', { 'ev-card' }))
  -- `.ev-pop` is a transparent, absolutely-positioned wrapper whose top padding
  -- bridges the visual gap to the claim (see evidence.head.html); the styled
  -- box lives on the inner `.ev-card`.
  local pop = pandoc.Span({ card }, pandoc.Attr('', { 'ev-pop' }, { role = 'note' }))
  el.content:insert(pop)

  -- Keyboard + screen-reader access: the claim is focusable, announces itself
  -- as a note, and `aria-description` carries a plain-text form of the quote +
  -- reference (the one attribute that survives the what-changed sanitizer
  -- intact, so assistive tech gets the evidence even where popover markup is
  -- rearranged).
  el.attributes['tabindex'] = '0'
  el.attributes['role'] = 'note'
  local aria = '“' .. quote .. '”'
  if source then aria = aria .. ' — ' .. source end
  if locator then aria = aria .. ' (' .. locator .. ')' end
  el.attributes['aria-description'] = aria

  return el
end

-- Load the store from metadata, THEN walk spans — a filter's Meta function runs
-- after element functions, so we drive the whole transform from Pandoc(doc)
-- where doc.meta is already available.
function Pandoc(doc)
  load_store(doc.meta)
  return doc:walk({ Span = transform })
end
