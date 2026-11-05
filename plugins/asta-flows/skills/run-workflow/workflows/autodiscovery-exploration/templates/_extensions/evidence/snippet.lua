--[[
  evidence/snippet.lua — supporting quotes for claims, opened from a marker.

  Every factual claim in the prose can carry the evidence that backs it, so a
  reader can check the source without leaving the text and a reviewer can see
  the backing quote directly in the "what-changed" diff. By default the claim
  stays plain text and a short bracketed marker after it, such as [J-6] or a
  citation [1], opens a popover with the verbatim quote and the source's full
  reference.

  A claim is a VERBATIM QUOTE plus a REFERENCE (with an optional locator). The
  quote text lives in an EXTERNAL keyed store (evidence.yml, merged into
  document metadata under `evidence:` via `metadata-files` in _quarto.yml). A
  claim in the .qmd then carries only a short key, which keeps the prose
  readable and puts the quotes in one structured file edited on its own:

      NatureBench has [90 tasks]{.ev key="naturebench-count"}.

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
    page     optional page on this site for the `source` (a path relative to
             the page, like a figure): the source text links to it, in the same
             tab, and `url` moves to a separate link after it
    locator  a NATIVE Pandoc/citeproc citation locator appended to the citation
             — e.g. "p. 4", "pp. 4-6", "sec. 3.2", "chap. 2", "abstract". This
             is Pandoc's own locator syntax (the part after the comma in
             `[@key, p. 4]`), so citeproc formats it in the site's citation
             style; we do NOT re-invent a locator format. See README.
    image    a figure from the source, shown at the top of the popover: a path
             relative to the page (like any figure) or an http(s) URL
    image_alt  the figure's alt text (default: "Figure from <source>")
    label    the short marker shown after the claim, e.g. "J-6" (default:
             derived from an AutoDiscovery `source`, "AutoDiscovery run J,
             experiment 6" -> J-6 and "AutoDiscovery run J (...)" -> J; else
             the entry's own citation for a `cite` entry)
  Inline attributes take precedence over the stored entry field by field.

  Document metadata options (defaults first):
    evidence-marker: label      the claim stays plain text and a short marker
                                after it opens the evidence: `[J-6]` from the
                                entry's `label`, or the entry's own citation
                                (`[1]`). A citation of the same work that
                                already follows the claim becomes the marker.
                                A span whose text is its label is the marker.
                     claim      the claim itself is underlined and opens the
                                evidence on hover or focus
    evidence-reference: full    a `cite` entry's popover shows the work's full
                                reference, formatted by citeproc exactly as in
                                the reference list; the locator and a Semantic
                                Scholar link (from any entry's provenance
                                corpus_id for that work) follow on a line of
                                their own
                        short   the short citation, as in the body text
    evidence-provenance: true   a collapsed "Source details" disclosure
                                shows an entry's provenance
                         false  provenance stays in evidence.yml only
    evidence-figures: true      an entry's `image` sits at the top of its
                                popover
                      false     no figures in popovers
    evidence-underline: always  (claim mode only) a dotted underline
                        hover   claims read as plain prose until hovered,
                                focused or open
  Links to sources open in a new tab.

  PROVENANCE — how the quote was obtained is RETAINED per entry under `provenance:`
  and reviewable in the evidence.yml diff, but is NOT shown by default in the
  popover: the primary view is just the quote and its reference (its
  `corpus_id` also gives the reference's Semantic Scholar link). Provenance
  sits behind a small, collapsed “Source details” disclosure so it is
  available on demand without overwhelming the read
  (`evidence-provenance: false` drops the disclosure). The schema is
  deliberately small and open. Record only facts the producer actually
  returned: use the exact CLI subcommand for `method`, and the canonical URI
  returned by an indexed Asta document for `url`. Omit fields that are unknown:
    provenance:
      method     exact producer invocation — e.g. "asta papers snippet-search"
      query      the search query that surfaced the quote (for search methods)
      corpus_id  S2 corpusId of the source paper (rendered as an S2 link)
      url        canonical link to the source or a produced artifact/report URI
      retrieved  ISO date the evidence was obtained
      note       free text

  The evidence is emitted as a real, hidden child span (`.ev-pop`) of the
  marker (or the claim) — not stuffed into a data-* attribute — so the quote and
  citation render as genuine markup on both the full site AND the workspace
  "what-changed" diff page, and a pure-CSS `:hover`/`:focus-within` reveal shows
  it (no JavaScript required). Because the popover is a DOM descendant of the
  marker, hovering it keeps the marker's `:hover` alive, so the popover never
  drops out from a gap between the marker and the box. For non-HTML output the
  filter leaves the document unchanged.
]]

-- The keyed evidence store, populated from document metadata in Pandoc(doc)
-- before any span is transformed.
local store = {}
-- Document-level options, read with the store (see the header for defaults).
local quiet = false
local show_prov = true
local show_figures = true
local marker_mode = true
local full_refs = true
-- Formatted full references (cite key -> Inlines) and Semantic Scholar corpus
-- IDs per cited work, for `evidence-reference: full`.
local full_ref = {}
local s2_by_cite = {}
-- Works shown as a full reference in some popover; see Pandoc(doc).
local in_popover = {}

local FIELDS = { 'quote', 'cite', 'source', 'url', 'page', 'locator', 'image', 'image_alt', 'label' }
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

-- A document option as one of `choices`; anything else warns and gives the
-- default (the first choice). YAML booleans arrive as Lua booleans.
local function option(meta, name, choices)
  local v = meta[name]
  if v == nil then return choices[1] end
  if type(v) ~= 'boolean' then v = pandoc.utils.stringify(v) end
  for _, c in ipairs(choices) do
    if v == c then return v end
  end
  io.stderr:write('[evidence] ' .. name .. ' must be ' .. tostring(choices[1]) .. ' or '
    .. tostring(choices[2]) .. ', not "' .. tostring(v) .. '"\n')
  return choices[1]
end

-- Read `evidence:` out of the document metadata into a plain lua table
-- { key = { quote = "...", cite = "...", ... } }. Metadata values arrive as
-- pandoc inline lists / MetaString, so each field is stringified to plain text.
local function load_store(meta)
  if meta == nil then return end
  marker_mode = option(meta, 'evidence-marker', { 'label', 'claim' }) == 'label'
  full_refs = option(meta, 'evidence-reference', { 'full', 'short' }) == 'full'
  show_prov = option(meta, 'evidence-provenance', { true, false })
  show_figures = option(meta, 'evidence-figures', { true, false })
  quiet = option(meta, 'evidence-underline', { 'always', 'hover' }) == 'hover'
  local ev = meta.evidence
  -- An empty YAML key (`evidence:`) is null rather than a map. Treat absent or
  -- malformed stores as empty so a freshly scaffolded workspace still renders.
  if type(ev) ~= 'table' then return end
  for key, entry in pairs(ev) do
    if type(entry) == 'table' then
      local rec = {}
      for _, f in ipairs(FIELDS) do
        if entry[f] ~= nil then
          local s = pandoc.utils.stringify(entry[f])
          if s ~= '' then rec[f] = s end
        end
      end
      rec.provenance = load_prov(entry.provenance)
      store[key] = rec
      if rec.cite and rec.provenance and rec.provenance.corpus_id then
        s2_by_cite[rec.cite] = rec.provenance.corpus_id
      end
    end
  end
end

-- Convert a plain-text locator into Pandoc inlines without adding Markdown's
-- citation separator. Citeproc owns the comma/spacing before the locator.
-- Smart typography reads "p. 4" as "p." and a no-break space; split there too
-- (Lua's %s works on bytes and would cut the UTF-8 no-break space in half).
local function locator_inlines(locator)
  local inlines = {}
  for word in locator:gsub('\u{00A0}', ' '):gmatch('[^ \t\r\n]+') do
    if #inlines > 0 then inlines[#inlines + 1] = pandoc.Space() end
    inlines[#inlines + 1] = pandoc.Str(word)
  end
  return inlines
end

-- A source link leaves the page, so it opens in a new tab and the reader keeps
-- their place in the text.
local NEW_TAB = pandoc.Attr('', {}, { target = '_blank', rel = 'noopener noreferrer' })
local NEW_TAB_HTML = ' target="_blank" rel="noopener noreferrer"'

local function html_escape(s)
  return (s:gsub('[&<>"]', {
    ['&'] = '&amp;', ['<'] = '&lt;', ['>'] = '&gt;', ['"'] = '&quot;',
  }))
end

-- Evidence URLs are author-controlled data that ultimately become hrefs. Keep
-- the supported set explicit so a malformed store cannot introduce an active
-- scheme such as javascript:. `asta:` is the one custom scheme this extension
-- intentionally supports for citable Asta document URIs.
local function safe_url(url)
  if url == nil then return nil end
  local scheme = url:match('^([%a][%w+%.%-]*):')
  if scheme == nil then return nil end
  scheme = scheme:lower()
  if scheme == 'https' or scheme == 'http' or scheme == 'asta' then return url end
  return nil
end

-- A figure is a path relative to the page or an http(s) URL; no other scheme.
local function safe_image(src)
  if src == nil then return nil end
  local scheme = src:match('^([%a][%w+%.%-]*):')
  if scheme == nil then return src end
  scheme = scheme:lower()
  if scheme == 'https' or scheme == 'http' then return src end
  return nil
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
  if prov == nil or not show_prov then return nil end
  local method = prov.method
  local summary = method and ('Source details — ' .. method) or 'Source details'

  local rows = {}
  if prov.query then
    rows[#rows + 1] = 'query: <em>“' .. html_escape(prov.query) .. '”</em>'
  end
  if prov.corpus_id then
    -- Link on api.semanticscholar.org: it takes a prefixed external ID and
    -- redirects to the paper page, while the www route takes a paperId only.
    rows[#rows + 1] = '<a href="https://api.semanticscholar.org/CorpusID:'
      .. html_escape(prov.corpus_id) .. '"' .. NEW_TAB_HTML .. '>S2 #'
      .. html_escape(prov.corpus_id) .. '</a>'
  end
  if prov.url then
    local href = safe_url(prov.url)
    if href then
      rows[#rows + 1] = '<a href="' .. html_escape(href) .. '"' .. NEW_TAB_HTML .. '>source ↗</a>'
    end
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

-- Format every cited work's full reference with citeproc, using the document's
-- own bibliography and CSL, so a popover shows the same text as the reference
-- list (minus the list's number). Failures fall back to the short citation.
local function load_full_refs(doc)
  local seen, keys = {}, {}
  local function add(key)
    if key and key ~= '' and not seen[key] then
      seen[key] = true
      keys[#keys + 1] = key
    end
  end
  for _, rec in pairs(store) do add(rec.cite) end
  doc:walk({ Span = function(el)
    if el.classes:includes('ev') then add(el.attributes.cite) end
  end })
  if #keys == 0 then return end
  table.sort(keys)
  local cites = {}
  for _, key in ipairs(keys) do
    cites[#cites + 1] = pandoc.Cite({ pandoc.Str('@' .. key) },
      { pandoc.Citation(key, 'NormalCitation') })
    cites[#cites + 1] = pandoc.Space()
  end
  local meta = pandoc.Meta({})
  for _, f in ipairs({ 'bibliography', 'csl', 'references', 'lang' }) do
    if doc.meta[f] ~= nil then meta[f] = doc.meta[f] end
  end
  meta.nocite = pandoc.MetaInlines(cites)
  local ok, res = pcall(pandoc.utils.citeproc, pandoc.Pandoc({}, meta))
  if not ok then
    io.stderr:write('[evidence] could not format full references: ' .. tostring(res) .. '\n')
    return
  end
  res:walk({ Div = function(d)
    local key = d.identifier:match('^ref%-(.+)$')
    if key == nil or not d.classes:includes('csl-entry') then return nil end
    local inl = pandoc.utils.blocks_to_inlines(d.content):walk({
      Span = function(sp)
        if sp.classes:includes('csl-left-margin') then return {} end
        if sp.classes:includes('csl-right-inline') then return sp.content end
      end,
      Link = function(l) l.attributes.target = '_blank'; l.attributes.rel = 'noopener noreferrer'; return l end,
    })
    while #inl > 0 and (inl[1].t == 'Space' or inl[1].t == 'SoftBreak') do inl:remove(1) end
    full_ref[key] = inl
  end })
end

-- The marker label for an entry with no `label`: "J-6" for an AutoDiscovery
-- experiment ("AutoDiscovery run J, experiment 6") and "J" for a run.
local function derive_label(source)
  if source == nil then return nil end
  local run, n = source:match('^AutoDiscovery run (%S+), experiment (%d+)')
  if run then return run .. '-' .. n end
  run = source:match('^AutoDiscovery run ([^%s,]+)')
  return run
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
  local href = safe_url(url)
  -- A page is a path relative to the citing page (or http(s)), like a figure.
  local page = safe_image(resolve(el, entry, 'page'))
  local locator = resolve(el, entry, 'locator')
  local image = show_figures and resolve(el, entry, 'image') or nil
  local src = safe_image(image)
  if image and not src then
    io.stderr:write('[evidence] image must be a relative path or http(s) URL: "' .. image .. '"\n')
  end
  local prov = entry and entry.provenance or nil
  local label = resolve(el, entry, 'label') or derive_label(source)

  -- Drop the authoring attributes so they don't render as stray HTML.
  for _, k in ipairs({ 'key', 'quote', 'cite', 'source', 'url', 'page', 'locator', 'image', 'image_alt', 'label' }) do
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
  local linkInlines = nil
  if cite and full_ref[cite] then
    srcInlines = pandoc.Inlines({ pandoc.Str('— ') })
    srcInlines:extend(full_ref[cite]:clone())
    -- The locator and a Semantic Scholar link, on a line of their own.
    linkInlines = pandoc.Inlines({})
    if locator then linkInlines:insert(pandoc.Str(locator)) end
    local s2 = (prov and prov.corpus_id) or s2_by_cite[cite]
    if s2 then
      if #linkInlines > 0 then linkInlines:insert(pandoc.Str(' · ')) end
      linkInlines:insert(pandoc.Link({ pandoc.Str('Semantic'), pandoc.Space(), pandoc.Str('Scholar') },
        'https://api.semanticscholar.org/CorpusID:' .. s2, '', NEW_TAB))
    end
    if #linkInlines == 0 then linkInlines = nil end
    in_popover[cite] = true
  elseif cite then
    local citation = pandoc.Citation(cite, 'NormalCitation')
    if locator then citation.suffix = locator_inlines(locator) end
    local citeEl = pandoc.Cite({ pandoc.Str('[' .. cite .. ']') }, { citation })
    srcInlines = { pandoc.Str('— '), citeEl }
  elseif source then
    local label = pandoc.Str(source)
    local srcNode
    if page then
      -- The source names a page on this site; keep the reader in this tab.
      srcNode = pandoc.Link({ label }, page)
    else
      srcNode = href and pandoc.Link({ label }, href, '', NEW_TAB) or label
    end
    srcInlines = { pandoc.Str('— '), srcNode }
    if locator then srcInlines[#srcInlines + 1] = pandoc.Str(', ' .. locator) end
    if page and href then
      srcInlines[#srcInlines + 1] = pandoc.Str(' · ')
      srcInlines[#srcInlines + 1] = pandoc.Link({ pandoc.Str('open'), pandoc.Space(), pandoc.Str('↗') }, href, '', NEW_TAB)
    end
  elseif href then
    srcInlines = { pandoc.Str('— '), pandoc.Link({ pandoc.Str(href) }, href, '', NEW_TAB) }
  end

  local cardChildren = { textSpan }
  -- The figure goes first, linked to its full-size file. A raw <img> (not a
  -- pandoc Image) so Quarto adds no figure, lightbox or block wrapper: the
  -- popover must stay phrasing content (see build_prov_details).
  if src then
    local alt = resolve(el, entry, 'image_alt')
      or ('Figure from ' .. (source or cite or 'the source'))
    table.insert(cardChildren, 1, pandoc.RawInline('html',
      '<a class="ev-img-link" href="' .. html_escape(src) .. '"' .. NEW_TAB_HTML
      .. '><img class="ev-img" src="' .. html_escape(src) .. '" alt="'
      .. html_escape(alt) .. '" loading="lazy"></a>'))
  end
  if srcInlines then
    cardChildren[#cardChildren + 1] = pandoc.Span(srcInlines, pandoc.Attr('', { 'ev-pop-src' }))
  end
  if linkInlines then
    cardChildren[#cardChildren + 1] = pandoc.Span(linkInlines, pandoc.Attr('', { 'ev-pop-links' }))
  end
  -- Provenance, retained but collapsed (dropped with `evidence-provenance: false`).
  local provDetails = build_prov_details(prov)
  if provDetails then cardChildren[#cardChildren + 1] = provDetails end

  local card = pandoc.Span(cardChildren, pandoc.Attr('', { 'ev-card' }))
  -- `.ev-pop` is a transparent, absolutely-positioned wrapper whose top padding
  -- bridges the visual gap to the claim (see evidence.head.html); the styled
  -- box lives on the inner `.ev-card`.
  local pop = pandoc.Span({ card },
    pandoc.Attr('', src and { 'ev-pop', 'ev-pop-figure' } or { 'ev-pop' }, { role = 'note' }))

  -- Marker mode (the default): the claim reads as plain text and only a short
  -- marker after it opens the evidence. The marker is the claim itself when its
  -- text is the label (e.g. a list of experiment IDs), else "[label]", else the
  -- entry's citation (rendered by citeproc in the body's style). A citation of
  -- the same work that already follows the claim takes the marker's place
  -- (merge_cites).
  local claim = nil
  if marker_mode then
    local text = pandoc.utils.stringify(el.content)
    if not (label and text == label) then
      claim = el.content
      if label then
        el.content = pandoc.Inlines({ pandoc.Str('[' .. label .. ']') })
      elseif cite then
        el.content = pandoc.Inlines({ pandoc.Cite({ pandoc.Str('[' .. cite .. ']') },
          { pandoc.Citation(cite, 'NormalCitation') }) })
        el.attributes['data-ev-cite'] = cite
      else
        el.content = pandoc.Inlines({ pandoc.Str('[source]') })
      end
    end
    el.classes:insert('ev-marker')
  end
  el.content:insert(pop)
  if quiet then el.classes:insert('ev-quiet') end

  -- Keyboard + screen-reader access: the claim is focusable, announces itself
  -- as a note, and `aria-description` carries a plain-text form of the quote +
  -- reference (the one attribute that survives the what-changed sanitizer
  -- intact, so assistive tech gets the evidence even where popover markup is
  -- rearranged).
  el.attributes['tabindex'] = '0'
  el.attributes['role'] = 'note'
  local aria = '“' .. quote .. '”'
  if cite then
    aria = aria .. ' — citation ' .. cite
  elseif source then
    aria = aria .. ' — ' .. source
  elseif href then
    aria = aria .. ' — source ' .. href
  end
  if locator then aria = aria .. ' (' .. locator .. ')' end
  el.attributes['aria-description'] = aria

  if claim then
    local out = pandoc.Inlines(claim)
    out:insert(pandoc.Str('\u{00A0}'))
    out:insert(el)
    return out
  end
  return el
end

-- In marker mode, "claim [1] [1]" would cite the same work twice when the prose
-- already cites it right after the claim. Move that existing citation into the
-- marker instead (keeping its own prefix, locator and suffix). A narrative
-- citation ("Vaswani et al. (2017) show") belongs to the next sentence, so it
-- stays where it is.
local function merge_cites(inlines)
  local out = pandoc.Inlines({})
  local i = 1
  while i <= #inlines do
    local x = inlines[i]
    local key = x.t == 'Span' and x.attributes['data-ev-cite'] or nil
    local sp, nxt = inlines[i + 1], inlines[i + 2]
    if key and sp and (sp.t == 'Space' or sp.t == 'SoftBreak') and nxt and nxt.t == 'Cite'
        and #nxt.citations == 1 and nxt.citations[1].id == key
        and nxt.citations[1].mode ~= 'AuthorInText' then
      x.content[1] = nxt
      x.attributes['data-ev-cite'] = nil
      out:insert(x)
      i = i + 3
    else
      if key then x.attributes['data-ev-cite'] = nil end
      out:insert(x)
      i = i + 1
    end
  end
  return out
end

-- Load the store from metadata, THEN walk spans — a filter's Meta function runs
-- after element functions, so we drive the whole transform from Pandoc(doc)
-- where doc.meta is already available.
function Pandoc(doc)
  if not FORMAT:match('html') then return doc end
  load_store(doc.meta)
  if full_refs then load_full_refs(doc) end
  doc = doc:walk({ Span = transform })
  if marker_mode then doc = doc:walk({ Inlines = merge_cites }) end
  -- A popover's full reference is plain text, not a citation, so a work cited
  -- only by a claim (with `evidence-marker: claim` or a `label`) would drop out
  -- of the reference list. Keep it there, as the short citation did; listing a
  -- work that the text also cites changes nothing.
  local keys = {}
  for key in pairs(in_popover) do keys[#keys + 1] = key end
  table.sort(keys)
  local nocite = pandoc.Inlines({})
  for _, key in ipairs(keys) do
    nocite:insert(pandoc.Cite({ pandoc.Str('@' .. key) }, { pandoc.Citation(key, 'NormalCitation') }))
    nocite:insert(pandoc.Space())
  end
  if #nocite > 0 then
    doc.meta.nocite = doc.meta.nocite == nil and pandoc.MetaInlines(nocite)
      or pandoc.MetaList({ doc.meta.nocite, pandoc.MetaInlines(nocite) })
  end
  return doc
end
