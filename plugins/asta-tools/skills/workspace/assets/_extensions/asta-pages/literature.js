/* asta-pages literature page: the product's Paper Finder panel, read-only.
   Reads the JSON the asta-literature shortcode embedded (#asta-literature-data: the run's
   papers and searches, written by the theory-generation workflow's data script) and draws the paper cards with a text
   filter, and a facets column: sort, fetch status, year, venue, author.
   #paper-<corpus id or key> in the address scrolls to that paper and marks it (filters that hide
   it are cleared; a copy shown once on another card goes to that card). Each search links its own
   file when the shortcode found it on disk (data-asta-search-files). Uses no browser storage. */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  function baseAnchor(p) { return "paper-" + (p.corpusId || p.key); }
  var CHEVRON = '<svg class="ap-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  var SORTS = [
    ["rank", "Search rank", function (a, b) { return (a.rank || 1e9) - (b.rank || 1e9); }],
    ["newest", "Newest first", function (a, b) { return (b.year || 0) - (a.year || 0); }],
    ["oldest", "Oldest first", function (a, b) { return (a.year || 1e9) - (b.year || 1e9); }],
    ["cited", "Most cited", function (a, b) { return (b.citationCount || 0) - (a.citationCount || 0); }],
    ["title", "Title", function (a, b) { return String(a.title).localeCompare(String(b.title)); }]
  ];
  var STATUS = { "full-text": "Full text", "metadata-only": "Abstract only", failed: "Fetch failed", timeout: "Fetch timed out" };
  // A paper's part in the run, in words a newcomer reads without a glossary. Data files written
  // before roles existed fall back to the fetch status.
  var ROLE = {
    used: ["Used by the theories", "Read in full; its findings are cited as evidence by at least one theory."],
    read: ["Read, not used", "Read in full, but no theory cites its findings."],
    abstract: ["Not read (abstract only)", "Only the abstract was available, so nothing was extracted from it."]
  };
  function role(p) { return p.role || (p.status === "full-text" ? "read" : "abstract"); }
  var FACETS = [
    ["role", "Part in this run", function (p) { return [ROLE[role(p)][0]]; }],
    // Decades, not single years: a reader filters a collection that spans the 1940s to now by era.
    ["year", "Decade", function (p) { return [p.year ? Math.floor(p.year / 10) * 10 + "s" : "Year unknown"]; }],
    ["venue", "Venue", function (p) { return p.venue ? [p.venue] : []; }],
    ["author", "Author", function (p) { return p.authors || []; }]
  ];
  var MAX_TERMS = 8;

  function authors(p) {
    var a = p.authors || [];
    if (!a.length) return "";
    return a.length > 4 ? a.slice(0, 3).join(", ") + " et al." : a.join(", ");
  }

  function card(p, i, prefix) {
    var meta = [authors(p), [p.venue, p.year].filter(Boolean).join(", "),
      p.citationCount != null ? plural(p.citationCount, "citation", "citations") : ""].filter(Boolean).map(esc).join(" · ");
    var chips = [];
    var r = ROLE[role(p)];
    chips.push('<span class="ap-chip' + (role(p) === "used" ? " ap-good" : "") + '" title="' + esc(r[1]) + '">' + esc(r[0]) + "</span>");
    if (p.findings) chips.push('<span class="ap-chip" title="Findings Theorizer extracted from its full text">' + plural(p.findings, "finding", "findings") + " extracted</span>");
    else if (p.findings === 0 && role(p) === "read") chips.push('<span class="ap-chip ap-warn" title="Theorizer saved no findings from its full text: it had none on the question, or the extraction failed. The run page says which.">No findings extracted</span>');
    if (p.relevance != null) chips.push('<span class="ap-chip" title="How well the search service judged it to match the question">Search relevance ' + esc(p.relevance) + " of 3</span>");
    if (p.rank != null) chips.push('<span class="ap-chip" title="Its position in the search it came from">Search result ' + esc(p.rank) + "</span>");
    var dups = (p.duplicates || []).map(function (d) {
      return [d.venue, d.year].filter(Boolean).join(", ") || "another record";
    });
    var href = p.url || (p.corpusId ? "https://www.semanticscholar.org/p/" + encodeURIComponent(p.corpusId) : "");
    var title = esc(p.title || "Untitled");
    return '<div class="ap-paper" id="' + esc((prefix || "") + baseAnchor(p)) + '"><div class="ap-paper-num">' + (i + 1) + '</div><div class="ap-paper-body">' +
      "<div>" + (href ? '<a class="ap-paper-title" href="' + esc(href) + '" target="_blank" rel="noopener">' + title + "</a>" : '<span class="ap-paper-title">' + title + "</span>") + "</div>" +
      (meta ? '<div class="ap-paper-meta">' + meta + "</div>" : "") +
      (chips.length ? '<div class="ap-chips">' + chips.join("") + "</div>" : "") +
      (dups.length ? '<div class="ap-paper-meta">Also found as ' + dups.map(esc).join("; ") + " (the same work, shown once).</div>" : "") +
      (p.tldr ? '<p class="ap-paper-tldr">' + esc(p.tldr) + "</p>" : "") +
      (p.abstract ? "<details><summary>" + CHEVRON + "Abstract</summary><p>" + esc(p.abstract) + "</p></details>" : "") +
      "</div></div>";
  }

  // opts.prefix namespaces this panel's anchors ("r1/" -> #r1/paper-123), as on the theory page.
  function render(root, data, opts) {
    opts = opts || {};
    var prefix = opts.prefix || "";
    var searchFiles = opts.searchFiles || {};
    var all = (data.papers || []).slice();
    var searches = data.searches || [];
    var counts = { used: 0, read: 0, abstract: 0 };
    all.forEach(function (p) { counts[role(p)] += 1; });
    var head = '<div class="ap-lit-searches">' +
      (searches.length ? "<div>" + searches.map(function (s) {
        var file = s.name && searchFiles[s.name];
        return "Search " + (s.query ? "<q>" + esc(s.query) + "</q>" : "<code>" + esc(s.name) + "</code>") + " returned " +
          plural(s.candidates || 0, "paper", "papers") +
          (file ? ' (<a href="' + esc(file) + '">' + esc(s.name + ".json") + "</a>)" : "");
      }).join("; ") + ". The papers below are the ones the run tried to read.</div>" : "") +
      "<div><strong>" + plural(all.length, "paper", "papers") + ":</strong> " +
      [counts.used + " used by the theories", counts.read + " read in full but not used",
       counts.abstract + " not read (only an abstract was available)"].join(", ") + ".</div></div>";
    if (!all.length) {
      root.innerHTML = head + '<div class="ap-empty"><strong>No papers yet</strong>The run has not fetched any papers.</div>';
      return;
    }
    var state = { text: "", sort: "rank", picked: {} };
    FACETS.forEach(function (f) { state.picked[f[0]] = {}; });

    root.innerHTML = head +
      '<div class="ap-lit"><div class="ap-lit-main">' +
      '<div class="ap-lit-bar"><span class="ap-count" aria-live="polite"></span>' +
      '<input type="search" placeholder="Filter by title, author, venue or abstract" aria-label="Filter papers"></div>' +
      '<div class="ap-papers"></div></div><div class="ap-facets" role="complementary" aria-label="Sort and filter"></div></div>';

    var list = root.querySelector(".ap-papers");
    var count = root.querySelector(".ap-count");
    var facetsEl = root.querySelector(".ap-facets");
    var q = root.querySelector('input[type="search"]');

    function matches(p, skip) {
      if (state.text) {
        var hay = [p.title, (p.authors || []).join(" "), p.venue, p.abstract, p.tldr].join(" ").toLowerCase();
        if (hay.indexOf(state.text) < 0) return false;
      }
      return FACETS.every(function (f) {
        if (f[0] === skip) return true;
        var want = Object.keys(state.picked[f[0]]);
        if (!want.length) return true;
        var have = f[2](p);
        return want.some(function (w) { return have.indexOf(w) >= 0; });
      });
    }

    function drawFacets() {
      var any = FACETS.some(function (f) { return Object.keys(state.picked[f[0]]).length; });
      var html = '<div class="ap-facet"><h4>Sort by</h4>' + SORTS.map(function (s) {
        return '<label><input type="radio" name="ap-sort" value="' + s[0] + '"' + (state.sort === s[0] ? " checked" : "") + "> " + s[1] + "</label>";
      }).join("") + "</div>";
      FACETS.forEach(function (f) {
        // A facet's counts ignore its own selection, so its other values stay pickable.
        var counts = {};
        all.filter(function (p) { return matches(p, f[0]); }).forEach(function (p) {
          f[2](p).forEach(function (v) { counts[v] = (counts[v] || 0) + 1; });
        });
        var terms = Object.keys(counts).sort(function (a, b) {
          if (f[0] !== "year") return (counts[b] - counts[a]) || a.localeCompare(b);
          // Newest decade first; "Year unknown" last.
          var ua = a === "Year unknown", ub = b === "Year unknown";
          return ua !== ub ? (ua ? 1 : -1) : b.localeCompare(a);
        });
        if (f[0] !== "year") terms = terms.slice(0, MAX_TERMS); // every decade is listed
        Object.keys(state.picked[f[0]]).forEach(function (v) { if (terms.indexOf(v) < 0) terms.push(v); });
        if (terms.length < 2 && !Object.keys(state.picked[f[0]]).length) return;
        html += '<div class="ap-facet"><h4>' + f[1] + "</h4>" + terms.map(function (v) {
          return '<label title="' + esc(v) + '"><input type="checkbox" data-facet="' + f[0] + '" value="' + esc(v) + '"' +
            (state.picked[f[0]][v] ? " checked" : "") + '> <span class="ap-term">' + esc(v) + '</span><span class="ap-n">' + (counts[v] || 0) + "</span></label>";
        }).join("") + "</div>";
      });
      if (any || state.text) html += '<div class="ap-facet"><button type="button" class="ap-clear">Clear filters</button></div>';
      facetsEl.innerHTML = html;
    }

    function update() {
      var sorter = SORTS.filter(function (s) { return s[0] === state.sort; })[0][2];
      var shown = all.filter(function (p) { return matches(p, null); }).sort(sorter);
      count.textContent = shown.length === all.length ? plural(all.length, "paper", "papers")
        : shown.length + " of " + plural(all.length, "paper", "papers");
      list.innerHTML = shown.length ? shown.map(function (p, i) { return card(p, i, prefix); }).join("")
        : '<div class="ap-empty"><strong>No papers match</strong>Clear a filter to see more.</div>';
      drawFacets();
    }

    q.addEventListener("input", function () { state.text = q.value.trim().toLowerCase(); update(); });
    facetsEl.addEventListener("change", function (e) {
      var t = e.target;
      if (t.name === "ap-sort") state.sort = t.value;
      else if (t.getAttribute("data-facet")) {
        var f = t.getAttribute("data-facet");
        if (t.checked) state.picked[f][t.value] = true; else delete state.picked[f][t.value];
      }
      update();
    });
    facetsEl.addEventListener("click", function (e) {
      if (!e.target.closest || !e.target.closest(".ap-clear")) return;
      FACETS.forEach(function (f) { state.picked[f[0]] = {}; });
      state.text = ""; q.value = ""; update();
    });
    update();

    function fromHash() {
      var id = "";
      try { id = decodeURIComponent((location.hash || "").slice(1)); } catch (e) { id = ""; }
      if (prefix) { if (id.indexOf(prefix) !== 0) return; id = id.slice(prefix.length); }
      if (!/^paper-/.test(id)) return;
      // A copy of a work is shown once, on the card that lists it under "Also found as".
      var want = id.slice("paper-".length);
      if (!all.some(function (p) { return (p.corpusId || p.key) === want; })) {
        var card = all.filter(function (p) {
          return (p.duplicates || []).some(function (d) { return d && (d.corpusId === want || d.key === want); });
        })[0];
        if (card) id = baseAnchor(card);
      }
      id = prefix + id;
      var el = document.getElementById(id);
      if (!el) { FACETS.forEach(function (f) { state.picked[f[0]] = {}; }); state.text = ""; q.value = ""; update(); el = document.getElementById(id); }
      if (!el) return;
      root.querySelectorAll(".ap-paper.ap-target").forEach(function (o) { o.classList.remove("ap-target"); });
      el.classList.add("ap-target");
      if (el.scrollIntoView) el.scrollIntoView({ block: "center" });
    }
    window.addEventListener("hashchange", fromHash);
    fromHash();
  }

  function safeRender(root, readData, opts) {
    try {
      render(root, readData(), opts);
    } catch (e) {
      root.innerHTML = '<div class="ap-error">The paper data could not be read (' + esc(e.message) +
        "). Write it again with the workflow's data script and render again.</div>";
    }
  }
  window.AstaPages = window.AstaPages || {};
  window.AstaPages.literature = safeRender;

  // A page that carries the Quarto shortcode's markup draws itself, its searches linking the
  // files the shortcode found.
  function start() {
    var root = document.querySelector(".asta-panel.asta-literature");
    var src = document.getElementById("asta-literature-data");
    if (!root || !src) return;
    var files = {};
    try { files = JSON.parse(root.getAttribute("data-asta-search-files") || "{}") || {}; } catch (e) { files = {}; }
    safeRender(root, function () { return JSON.parse(src.textContent); }, { searchFiles: files });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
