/* asta-pages theory page: the product's Theorizer panel.
   Reads the JSON the asta-theories shortcode embedded (script.asta-theories-data, one per data
   file, written by the theory-generation workflow's data script) and draws the list of theories
   with supporting and conflicting counts, then the selected theory's statements, predictions,
   evidence and referenced papers. Theories are grouped by the query they were generated for:
   one query is shown above the table; several get a tab each.
   Anchors: #theory-<n> selects a theory, #finding-<uuid> opens the Evidence tab at that row,
   #query-<n> selects a query's tab. Choosing a theory or a tab is a step in the history (Back
   returns to the list or the tab before). A paper's title links to its entry on the site's
   papers page (#paper-<corpus id or key>), which the shortcode names. With the shortcode's
   tests=, each theory's tests (script.asta-theories-tests, matched by theory name) add a verdict
   column to the table and a Tests tab, drawn with tests.js. Uses no browser storage. */
(function () {
  "use strict";

  // The address as this panel's page sees it: asta-pages.js knows which page of a flow's feed
  // the panel came from (null when the address is another page's); without it, the page's own.
  function api() { return typeof window !== "undefined" ? window.AstaPages : null; }
  function hashOf(el) { var A = api(); return A && A.hashOf ? A.hashOf(el) : location.hash; }
  function urlOf(el, hash) { var A = api(); return A && A.urlOf ? A.urlOf(el, hash) : hash; }
  function scopeOf(el) { var A = api(); return A && A.scope ? A.scope(el) : (typeof document !== "undefined" ? document : null); }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  // A theory's anchor is its id when that already reads "theory-N" (Theorizer's ids do).
  function baseAnchor(t) { var id = String(t.id); return /^theory-/.test(id) ? id : "theory-" + id; }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  function sentenceCase(s) {
    s = String(s || "").replace(/[_-]+/g, " ").trim();
    return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
  }
  function cell(v) {
    if (v == null || v === "") return "—";
    if (typeof v === "boolean") return v ? "Yes" : "No";
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }
  var CHEVRON = '<svg class="ap-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var ICON = {
    support: '<svg class="ap-ev-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3 3 7-7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    conflict: '<svg class="ap-ev-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    open: '<svg class="ap-ev-icon" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 5.5v3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="8" cy="10.8" r="0.9" fill="currentColor"/></svg>'
  };

  // Novelty labels, as the product's Theorizer panel words them.
  var NOVELTY = {
    conceptual_reframing_abstraction: "Reframing", constraint_limitation: "Boundary",
    empirical_synthesis_meta_regulariry: "Pattern", empirical_synthesis_meta_regularity: "Pattern",
    explanatory_mechanistic: "Mechanism", generalization_scope_expansion: "Scope",
    phenomenon_effect: "Effect", unification: "Unification"
  };
  var DEGREE = {
    derivable_unstated: "Implied", explicit_established: "Established",
    explicit_peripheral: "Prior work", genuinely_new: "Likely novel"
  };

  function isNovel(st) {
    var n = st.novelty || {};
    if ((n.dimensions || []).some(function (d) { return d.degree === "genuinely_new"; })) return true;
    return /^(new|genuinely[ -]new|likely[ -]new)\b/i.test(String(n.label || ""));
  }
  var NOVEL_CHIP = '<span class="ap-chip ap-novel">Likely novel</span>';

  // A paper's title links to its entry on the site's papers page (the shortcode's papers="...",
  // "literature.html" by default), anchored #paper-<corpus id or key> as the paper list anchors
  // it; that page marks the entry and scrolls to it. The entry links out to the paper's record.
  var PAPERS_PAGE = "literature.html";
  function paperLink(p, cls, papersPage) {
    if (!p) return "";
    var title = esc(p.title || "Untitled"), id = p.corpusId || p.key;
    if (!id) return '<span class="' + cls + '">' + title + "</span>";
    return '<a class="' + cls + '" href="' + esc((papersPage || PAPERS_PAGE) + "#paper-" + encodeURIComponent(id)) + '">' + title + "</a>";
  }
  // "claude-opus-5" -> "Claude Opus 5"; a provider prefix ("openai/") is dropped.
  function modelName(m) {
    m = String(m || "").split("/").pop();
    return m.split("-").map(function (w) { return w.charAt(0).toUpperCase() + w.slice(1); }).join(" ").replace(/(\d) (\d)/g, "$1.$2");
  }
  // The theory's own novelty verdict; the statements carry their own.
  function theoryNovel(t) {
    return /^(new|genuinely[ -]new|likely[ -]new)\b/i.test(String((t.novelty || {}).label || ""));
  }
  function authors(p) {
    var a = p.authors || [];
    if (!a.length) return "";
    return a.length > 4 ? a.slice(0, 3).join(", ") + " et al." : a.join(", ");
  }
  function paperCard(p, i, link) {
    var meta = [authors(p), [p.venue, p.year].filter(Boolean).join(", ")].filter(Boolean).map(esc).join(" · ");
    return '<div class="ap-paper"><div class="ap-paper-num">' + (i + 1) + '</div><div class="ap-paper-body">' +
      "<div>" + link(p, "ap-paper-title") + "</div>" +
      (meta ? '<div class="ap-paper-meta">' + meta + "</div>" : "") +
      (p.abstract ? "<details><summary>" + CHEVRON + "Abstract</summary><p>" + esc(p.abstract) + "</p></details>" : "") +
      "</div></div>";
  }
  function empty(title, hint) {
    return '<div class="ap-empty"><strong>' + esc(title) + "</strong>" + esc(hint || "") + "</div>";
  }

  function statementsTab(t, papers, link) {
    if (!t.statements || !t.statements.length) return empty("No statements", "This theory has no statements in the data file.");
    return '<p class="ap-legend">A theory is a few statements, each a general claim (a law). Open one for its scope, how new it is, and the findings it cites for and against it.</p>' +
      '<div class="ap-stmts">' + t.statements.map(function (st, i) {
      var body = [];
      if (st.statement) body.push("<p>" + esc(st.statement) + "</p>");
      if (st.scope) body.push('<div class="ap-section"><div class="ap-label">Domain scope</div><p>' + esc(st.scope) + "</p></div>");
      var n = st.novelty || {};
      if (n.label || n.explanation || (n.dimensions && n.dimensions.length)) {
        var dims = (n.dimensions || []).map(function (d) {
          var label = (NOVELTY[d.key] || sentenceCase(d.key)) + (d.degree ? " (" + (DEGREE[d.degree] || sentenceCase(d.degree)) + ")" : "");
          var detail = [["What is introduced", d.introduced], ["What is known", d.known], ["What is novel", d.novel]]
            .filter(function (x) { return x[1]; })
            .map(function (x) { return "<div><strong>" + x[0] + ".</strong> " + esc(x[1]) + "</div>"; }).join("");
          return "<details><summary><span class=\"ap-chip" + (d.degree === "genuinely_new" ? " ap-novel" : "") + "\">" + esc(label) + "</span></summary><div>" + detail + "</div></details>";
        }).join("");
        body.push('<div class="ap-section"><div class="ap-label">Novelty</div>' +
          (n.label ? '<div class="ap-chips"><span class="ap-chip' + (isNovel(st) ? " ap-novel" : "") + '">' + esc(sentenceCase(n.label)) + "</span></div>" : "") +
          (n.explanation ? "<p>" + esc(n.explanation) + "</p>" : "") +
          (dims ? '<div class="ap-dims">' + dims + "</div>" : "") + "</div>");
      }
      function refs(label, list, kind) {
        if (!list || !list.length) return;
        body.push('<div class="ap-section"><div class="ap-label">' + label + '</div><div class="ap-ev-list">' + list.map(function (ev) {
          var p = ev.paper ? papers[ev.paper] : null;
          return '<div class="ap-ev-item ap-' + kind + '">' + ICON[kind] + "<div><div>" + esc(ev.text) + "</div>" +
            (p ? link(p, "ap-ev-paper") : "") + "</div></div>";
        }).join("") + "</div></div>");
      }
      refs("Evidence", st.evidence, "support");
      refs("Conflicting evidence", st.conflicting, "conflict");
      refs("Not accounted for", st.unaccounted, "open");
      if (st.special_cases && st.special_cases.length) {
        body.push('<div class="ap-section"><div class="ap-label">Special cases</div><ul class="ap-list">' +
          st.special_cases.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul></div>");
      }
      return '<details class="ap-stmt"' + (i === 0 ? " open" : "") + "><summary>" + CHEVRON +
        '<span class="ap-stmt-title">' + esc(st.name || "Statement " + (i + 1)) + (isNovel(st) ? NOVEL_CHIP : "") + "</span>" +
        (st.plain ? '<span class="ap-stmt-brief">' + esc(st.plain) + "</span>" : "") +
        '</summary><div class="ap-stmt-body">' + body.join("") + "</div></details>";
    }).join("") + "</div>";
  }

  function predictionsTab(t) {
    var groups = [["Likely outcomes", t.predictions_likely], ["Unknown outcomes", t.predictions_unknown],
                  ["Experiments that would count against it", t.negative_experiments]]
      .filter(function (g) { return g[1] && g[1].length; });
    if (!groups.length) return empty("No predictions", "Theorizer wrote no predictions for this theory.");
    return '<div class="ap-pred">' + groups.map(function (g) {
      return '<div class="ap-section"><div class="ap-label">' + g[0] + '</div><ul class="ap-list">' +
        g[1].map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul></div>";
    }).join("") + "</div>";
  }

  function evidenceTab(t, papers, findings, prefix, link) {
    prefix = prefix || "";
    var wanted = {};
    (t.evidence_results || []).forEach(function (r) { wanted[r] = true; });
    var out = Object.keys(findings || {}).map(function (sid) {
      var tb = findings[sid], cols = tb.columns || [];
      var rows = (tb.rows || []).filter(function (r) { return wanted[r.result]; });
      if (!rows.length) return "";
      var head = "<th>Paper</th><th>Finding</th>" + cols.map(function (c) {
        return '<th title="' + esc(c.description || "") + '">' + esc(sentenceCase(c.name)) + "</th>";
      }).join("");
      var body = rows.map(function (r) {
        var p = papers[r.paper], d = r.data || {};
        return '<tr id="' + esc(prefix) + 'finding-' + esc(r.uuid || "") + '"><td>' + (p ? link(p, "ap-ev-paper") : "—") + "</td>" +
          '<td class="ap-finding"><strong>' + esc(d.name_short || d.name_full || "") + "</strong>" +
          (d.brief_description ? esc(d.brief_description) : "") + "</td>" +
          cols.map(function (c) { return "<td>" + esc(cell(d[c.name])) + "</td>"; }).join("") + "</tr>";
      }).join("");
      return '<div class="ap-ev-schema"><p class="ap-legend">The findings Theorizer extracted from the full text of each paper behind this theory, one row per finding. The columns are the fields it was asked to fill; the question it was asked follows.</p>' +
        '<p class="ap-ev-query"><strong>' + esc(sid) + "</strong>" + esc(tb.query || "") +
        " <span class=\"ap-muted\">(" + plural(rows.length, "finding", "findings") + ")</span></p>" +
        '<div class="ap-ev-table-wrap"><table class="ap-ev-table"><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table></div></div>";
    }).filter(Boolean);
    return out.length ? out.join("") : empty("No evidence", "No extracted findings back this theory in the data file.");
  }

  // The tests run on a theory, each as a card: its verdict, effect, p and animals, and links to
  // its files (tests.js draws the card, as for an opened row of a tests table).
  function testsTab(tests, scope) {
    var lib = window.AstaPages.testsLib;
    if (!tests.length) return empty("No tests", "No test in the test index names this theory.");
    var t = lib.tally(tests);
    return '<p class="ap-legend">' + esc(t.text) + ". Each test's verdict is read from its result_summary.json; open its files for the design, code and result.</p>" +
      '<div class="ap-ts-cards">' + tests.map(function (x) {
        var here = scope && scope.querySelector && scope.querySelector('[id="test-' + String(x.id).replace(/[^A-Za-z0-9_.-]+/g, "-") + '"]');
        return lib.card(x, { head: true }).replace('<strong class="ap-ts-id">' + esc(x.id) + "</strong>",
          here ? '<a class="ap-ts-id" href="#' + esc(here.id) + '">' + esc(x.id) + "</a>" : '<strong class="ap-ts-id">' + esc(x.id) + "</strong>");
      }).join("") + "</div>";
  }

  function papersTab(t, papers, link) {
    var list = [];
    (t.papers || []).forEach(function (k) { var p = papers[k]; if (p && list.indexOf(p) < 0) list.push(p); });
    if (!list.length) return empty("No referenced papers", "None of this theory's evidence names a paper in the run.");
    return '<h3 class="ap-papers-head">' + plural(list.length, "paper", "papers") + " referenced</h3>" +
      '<div class="ap-papers">' + list.map(function (p, i) { return paperCard(p, i, link); }).join("") + "</div>";
  }

  // A query's identity: the same text, whatever its spacing.
  function normQuery(q) { return String(q == null ? "" : q).replace(/\s+/g, " ").trim(); }
  // "data/theorizer-v2.json" -> "theorizer-v2", to tell one data file's anchors from another's.
  function sourceStem(rel, i) {
    var name = String(rel || "").split("/").pop().replace(/\.json$/i, "").replace(/[^A-Za-z0-9_-]+/g, "-");
    return name || "source-" + (i + 1);
  }

  // The query a group of theories was generated for, above its table.
  function queryBlock(text) {
    return '<figure class="ap-query"><figcaption class="ap-label">Theory query</figcaption>' +
      "<blockquote>" + esc(text) + "</blockquote></figure>";
  }

  // The words a tab can show for each query: what follows the opening the queries share
  // ("Build theories, expressed as IF ... THEN laws, about ..."), cut to about 60 characters.
  function excerpts(queries) {
    var shared = 0;
    if (queries.length > 1) {
      var first = queries[0];
      shared = first.length;
      queries.forEach(function (q) {
        var k = 0;
        while (k < shared && k < q.length && q.charAt(k) === first.charAt(k)) k++;
        shared = k;
      });
      // Back up to a word boundary so an excerpt starts on a whole word.
      while (shared > 0 && /\S/.test(first.charAt(shared - 1))) shared--;
    }
    return queries.map(function (q) {
      var s = q.slice(shared).trim() || q;
      return s.length > 60 ? s.slice(0, 58).replace(/\s+\S*$/, "") + "…" : s;
    });
  }

  // One query's theories: the table, its legend and the selected theory. Returns what the page
  // needs to drive it: select(i, scroll), and whether a theory is selected yet.
  function drawGroup(box, group, prefix, link, visit, withTests) {
    var theories = group.entries.map(function (e) { return e.t; });
    var lib = window.AstaPages && window.AstaPages.testsLib;
    withTests = withTests && !!lib;
    function testsCell(e) {
      if (!e.tests.length) return '<td class="ap-tt-tests"><span class="ap-muted">\u2014</span></td>';
      var t = lib.tally(e.tests);
      return '<td class="ap-tt-tests"><span class="ap-ts-dot ap-v-' + t.key + '"></span>' + esc(t.text) + "</td>";
    }
    var rows = theories.map(function (t, i) {
      var novel = theoryNovel(t) ? NOVEL_CHIP : "";
      function count(n, papersN) {
        return (n || 0) + (papersN != null && n ? ' <span class="ap-from">from ' + plural(papersN, "paper", "papers") + "</span>" : "");
      }
      return '<tr data-i="' + i + '"><td><div class="ap-tt-name-cell"><span class="ap-tt-name">' + esc(t.name) + "</span>" + novel + "</div></td>" +
        '<td class="ap-num">' + count(t.supporting, t.supporting_papers) + '</td><td class="ap-num' + (t.conflicting ? " ap-has-conflict" : "") + '">' +
        count(t.conflicting, t.conflicting_papers) + "</td>" + (withTests ? testsCell(group.entries[i]) : "") + "</tr>";
    }).join("");
    box.innerHTML =
      '<div class="ap-tt"><button type="button" class="ap-tt-head" aria-expanded="true">' + CHEVRON + "<h2>" +
      plural(theories.length, "theory", "theories") + ' generated</h2></button><div class="ap-tt-wrap"><table><thead><tr>' +
      '<th>Theory name</th><th class="ap-num">Supporting evidence</th><th class="ap-num">Conflicting evidence</th>' +
      (withTests ? '<th class="ap-tt-tests">Tests</th>' : "") +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>" +
      '<p class="ap-legend">Counts are pieces of evidence: findings from the papers that a theory\'s statements cite for or against them, added up over its statements, and how many papers they come from. One paper can supply many.' +
      (withTests ? " Tests: how many of the tests run on a theory met their committed threshold." : "") + "</p>" +
      '</div><div class="ap-theory"></div>';

    var detail = box.querySelector(".ap-theory");
    var tt = box.querySelector(".ap-tt");
    var toggle = box.querySelector(".ap-tt-head");
    toggle.addEventListener("click", function () {
      var collapsed = tt.classList.toggle("ap-collapsed");
      toggle.setAttribute("aria-expanded", String(!collapsed));
    });
    var current = -1;

    function select(i, scroll) {
      var e = group.entries[i], t = e.t, src = e.src;
      current = i;
      box.querySelectorAll(".ap-tt tbody tr").forEach(function (r) { r.classList.toggle("ap-selected", +r.getAttribute("data-i") === i); });
      var nStatements = (t.statements || []).length;
      var tabs = [
        ["statements", plural(nStatements, "Statement", "Statements"), statementsTab(t, src.papers, link)],
        ["predictions", "Predictions", predictionsTab(t)],
        ["evidence", "Evidence", evidenceTab(t, src.papers, src.findings, prefix, link)],
        ["papers", "Referenced papers", papersTab(t, src.papers, link)]
      ];
      if (withTests) tabs.push(["tests", "Tests" + (e.tests.length ? " (" + e.tests.length + ")" : ""), testsTab(e.tests, scopeOf(box))]);
      var chips = [t.kind ? sentenceCase(t.kind) + " theory" : "",
        t.novelty && t.novelty.label ? "Novelty: " + sentenceCase(t.novelty.label) : "",
        t.model ? "Written by " + modelName(t.model) : ""].filter(Boolean);
      detail.id = prefix + e.anchor;
      detail.innerHTML = '<div class="ap-theory-head"><h2>' + esc(t.name) +
        '<a class="ap-anchor" href="#' + esc(prefix + e.anchor) + '" title="Link to this theory">#</a></h2>' +
        (t.summary ? "<p>" + esc(t.summary) + "</p>" : "") +
        (chips.length ? '<div class="ap-chips">' + chips.map(function (x) { return '<span class="ap-chip">' + esc(x) + "</span>"; }).join("") + "</div>" : "") +
        "</div>" +
        '<div class="ap-tabs" role="tablist">' + tabs.map(function (x, k) {
          return '<button type="button" class="ap-tab" role="tab" data-tab="' + x[0] + '" aria-selected="' + (k === 0) + '">' + esc(x[1]) + "</button>";
        }).join("") + "</div>" +
        tabs.map(function (x, k) {
          return '<div class="ap-tabpanel" role="tabpanel" data-panel="' + x[0] + '"' + (k === 0 ? "" : " hidden") + ">" + x[2] + "</div>";
        }).join("");
      detail.querySelectorAll(".ap-tab").forEach(function (b) {
        b.addEventListener("click", function () {
          var name = b.getAttribute("data-tab");
          detail.querySelectorAll(".ap-tab").forEach(function (o) { o.setAttribute("aria-selected", String(o === b)); });
          detail.querySelectorAll(".ap-tabpanel").forEach(function (p) { p.hidden = p.getAttribute("data-panel") !== name; });
        });
      });
      if (scroll && detail.scrollIntoView) detail.scrollIntoView({ block: "start" });
    }

    box.querySelectorAll(".ap-tt tbody tr").forEach(function (r) {
      r.addEventListener("click", function () {
        var i = +r.getAttribute("data-i");
        // A step in the history, so Back returns to where the reader chose it (the list).
        visit("#" + prefix + group.entries[i].anchor);
        select(i, true);
      });
    });

    return {
      select: select,
      selected: function () { return current; },
      // Open the Evidence tab and mark a finding's row in it.
      showFinding: function (uuid) {
        var tab = detail.querySelector('.ap-tab[data-tab="evidence"]');
        if (tab) tab.click();
        var row = null;
        detail.querySelectorAll("tr[id]").forEach(function (r) { if (r.id === prefix + "finding-" + uuid) row = r; });
        if (row) { row.classList.add("ap-target"); if (row.scrollIntoView) row.scrollIntoView({ block: "center" }); }
      }
    };
  }

  // input is one data file's JSON or a list of them (one per Theorizer project). Theories that
  // appear in more than one file (same id and name) are shown once. Theories are grouped by the
  // query they were generated for: one query shows it above the table; several give a tab each.
  // opts.prefix namespaces this panel's anchors ("r1/" -> #r1/theory-2), so several runs can
  // share one page; the Quarto pages use no prefix. opts.sources names each file (its path, for
  // anchors when two files use the same theory id); opts.names labels the query tabs in order;
  // opts.papers is the site's papers page, where a paper's title links.
  function render(root, input, opts) {
    opts = opts || {};
    var prefix = opts.prefix || "";
    var list = (Array.isArray(input) ? input : [input]).filter(function (d) { return d && typeof d === "object"; });
    var sources = list.map(function (d, s) {
      var papers = {};
      // A copy of a work shown once (p.duplicates) stands for the card that lists it.
      (Array.isArray(d.papers) ? d.papers : []).forEach(function (p) {
        papers[p.key] = p;
        (p.duplicates || []).forEach(function (c) { if (c && c.key && !papers[c.key]) papers[c.key] = p; });
      });
      (Array.isArray(d.papers) ? d.papers : []).forEach(function (p) { papers[p.key] = p; });
      return { data: d, papers: papers, findings: d.findings || {}, stem: sourceStem((opts.sources || [])[s], s) };
    });

    var seen = {}, anchors = {}, groups = [], byQuery = {}, nPapers = 0;
    sources.forEach(function (src) {
      nPapers += (Array.isArray(src.data.papers) ? src.data.papers : []).length;
      (src.data.theories || []).forEach(function (t) {
        var key = String(t.id) + "\u0000" + String(t.name || "");
        if (seen[key]) return;
        seen[key] = true;
        // Two projects both number their theories from theory-1: the later file's take its name.
        var anchor = baseAnchor(t);
        if (anchors[anchor]) anchor = src.stem + "/" + anchor;
        for (var n = 2; anchors[anchor]; n++) anchor = src.stem + "/" + baseAnchor(t) + "-" + n;
        anchors[anchor] = true;
        var text = t.query != null ? t.query : src.data.request;
        var q = normQuery(text);
        if (!Object.prototype.hasOwnProperty.call(byQuery, q)) {
          byQuery[q] = groups.length;
          groups.push({ query: q, text: String(text == null ? "" : text).trim(), entries: [] });
        }
        groups[byQuery[q]].entries.push({ t: t, src: src, anchor: anchor });
      });
    });
    // A test names its theory (theory_name): matched to the theory of that name, exactly, then
    // with spacing ignored.
    var tests = Array.isArray(opts.tests) ? opts.tests : null, unmatched = [];
    if (tests) {
      var exact = {}, loose = {};
      groups.forEach(function (g) {
        g.entries.forEach(function (e) {
          e.tests = [];
          var n = String(e.t.name || "");
          if (!exact[n]) exact[n] = e;
          if (!loose[normQuery(n)]) loose[normQuery(n)] = e;
        });
      });
      tests.forEach(function (x) {
        var n = x && x.index && x.index.theory_name != null ? String(x.index.theory_name) : null;
        var e = n == null ? null : exact[n] || loose[normQuery(n)];
        if (e) e.tests.push(x); else if (x) unmatched.push(x);
      });
    }
    if (!groups.length) {
      root.innerHTML = empty("No theories yet",
        "This run has " + plural(nPapers, "paper", "papers") + "; its theories appear here after the next generation.");
      return;
    }

    var names = opts.names || [];
    var short = excerpts(groups.map(function (g) { return g.query; }));
    var ids = groups.map(function (g, k) { return (root.id || "asta-theories") + "-q" + (k + 1); });
    if (groups.length > 1) {
      root.innerHTML = '<div class="ap-tabs ap-qtabs" role="tablist" aria-label="Theory queries">' + groups.map(function (g, k) {
        var label = names[k] ? String(names[k]) : "Query " + (k + 1);
        return '<button type="button" class="ap-tab ap-qtab" role="tab" id="' + ids[k] + '-tab" aria-controls="' + ids[k] +
          '" aria-selected="' + (k === 0) + '" tabindex="' + (k === 0 ? "0" : "-1") + '" data-q="' + k + '" title="' + esc(g.query.slice(0, 300)) + '">' +
          '<span class="ap-qtab-label">' + esc(label) + ' <span class="ap-count">· ' + plural(g.entries.length, "theory", "theories") + "</span></span>" +
          (g.query && !names[k] ? '<span class="ap-qtab-excerpt">' + esc(short[k]) + "</span>" : "") + "</button>";
      }).join("") + "</div>" + groups.map(function (g, k) {
        return '<div class="ap-qpanel" role="tabpanel" id="' + ids[k] + '" aria-labelledby="' + ids[k] + '-tab"' + (k === 0 ? "" : " hidden") + ">" +
          (g.query ? queryBlock(g.text) : "") + '<div class="ap-qbody"></div></div>';
      }).join("");
    } else {
      root.innerHTML = (groups[0].query ? queryBlock(groups[0].text) : "") + '<div class="ap-qbody"></div>';
    }
    var papersPage = opts.papers || "";
    function link(p, cls) { return paperLink(p, cls, papersPage); }
    // Choosing a theory or a query tab is a step in the browser's history (pushState), so Back
    // returns to the list or the tab before. `shown` is the address the panel last drew, so the
    // panel's own steps, and a Back that fires both popstate and hashchange, are drawn once.
    var shown = hashOf(root);
    function visit(hash) {
      if (hashOf(root) === hash) return;
      var url = urlOf(root, hash);
      try { history.pushState(null, "", url); } catch (e) {
        try { history.replaceState(null, "", url); } catch (x) { /* a sandboxed frame may refuse */ }
      }
      shown = hashOf(root);
    }
    var bodies = root.querySelectorAll(".ap-qbody");
    var views = groups.map(function (g, k) { return drawGroup(bodies[k], g, prefix, link, visit, !!tests); });
    if (unmatched.length) {
      var note = document.createElement("p");
      note.className = "ap-legend ap-tt-unmatched";
      note.textContent = plural(unmatched.length, "test names", "tests name") + " a theory not on this page: " +
        unmatched.map(function (x) { return x.id; }).join(", ") + ".";
      root.appendChild(note);
    }
    var qtabs = root.querySelectorAll(".ap-qtab"), qpanels = root.querySelectorAll(".ap-qpanel");
    var active = 0;

    function activate(k, focus) {
      active = k;
      qtabs.forEach(function (b, j) {
        b.setAttribute("aria-selected", String(j === k));
        b.setAttribute("tabindex", j === k ? "0" : "-1");
      });
      qpanels.forEach(function (p, j) { p.hidden = j !== k; });
      if (focus && qtabs[k] && qtabs[k].focus) qtabs[k].focus();
      if (views[k].selected() < 0) views[k].select(0, false);
    }
    // Another tab is a step in the history; the tab already shown is none.
    function choose(k, focus) {
      var from = active;
      activate(k, focus);
      if (k !== from) visit("#" + prefix + "query-" + (k + 1));
    }
    qtabs.forEach(function (b, k) {
      b.addEventListener("click", function () { choose(k, false); });
      // Arrow keys, Home and End move between the queries, as in any tab list.
      b.addEventListener("keydown", function (ev) {
        var to = { ArrowRight: k + 1, ArrowLeft: k - 1, Home: 0, End: qtabs.length - 1 }[ev.key];
        if (to == null) return;
        ev.preventDefault();
        choose((to + qtabs.length) % qtabs.length, true);
      });
    });

    function locate(match) {
      var at = null;
      groups.some(function (g, k) {
        var i = g.entries.findIndex(match);
        if (i >= 0) at = [k, i];
        return at !== null;
      });
      return at;
    }
    function fromHash() {
      var h = hashOf(root) || "";
      try { h = decodeURIComponent(h.slice(1)); } catch (e) { h = ""; }
      if (!h) {
        // No fragment: the page as it first opened (Back to it from a theory or a tab).
        activate(0, false);
        if (views[0].selected() !== 0) views[0].select(0, false);
        return;
      }
      if (prefix) {
        if (h.indexOf(prefix) !== 0) { activate(active, false); return; }
        h = h.slice(prefix.length);
      }
      var m = /^query-(\d+)$/.exec(h);
      if (m && +m[1] >= 1 && +m[1] <= groups.length) { activate(+m[1] - 1, false); return; }
      if (/^finding-/.test(h)) {
        // A finding lives in the Evidence tab of every theory built on its extraction result.
        var uuid = h.slice("finding-".length);
        var hit = locate(function (e) {
          var result = null;
          Object.keys(e.src.findings).forEach(function (sid) {
            (e.src.findings[sid].rows || []).forEach(function (r) { if (r.uuid === uuid) result = r.result; });
          });
          return result != null && (e.t.evidence_results || []).indexOf(result) >= 0;
        });
        if (hit) {
          activate(hit[0], false);
          views[hit[0]].select(hit[1], false);
          views[hit[0]].showFinding(uuid);
          return;
        }
      }
      var found = h ? (locate(function (e) { return e.anchor === h; }) ||
                       locate(function (e) { return String(e.t.id) === h; })) : null;
      if (found) {
        activate(found[0], false);
        views[found[0]].select(found[1], true);
      } else {
        activate(active, false);
      }
    }
    // Back and Forward fire popstate, and hashchange too when the fragment differs; a link or
    // the app's site frame fires hashchange alone.
    function onAddress() {
      var h = hashOf(root);
      if (h == null || h === shown) return; // another page's address, or this panel's own step
      shown = h;
      fromHash();
    }
    window.addEventListener("hashchange", onAddress);
    window.addEventListener("popstate", onAddress);
    fromHash();
  }

  function safeRender(root, readData, opts) {
    try {
      render(root, readData(), opts);
    } catch (e) {
      root.innerHTML = '<div class="ap-error">The theory data could not be read (' + esc(e.message) +
        "). Write it again with the workflow's data script and render again.</div>";
    }
  }
  window.AstaPages = window.AstaPages || {};
  window.AstaPages.theories = safeRender;

  // Each theories panel in scope draws itself, once: one embedded data file per Theorizer
  // project the shortcode names (script.asta-theories-data, in the shortcode's order) and its
  // tests (script.asta-theories-tests), the scripts that follow the panel. asta-pages.js calls
  // start on a page appended to a flow's feed, so a document can hold several pages' panels.
  var drawn = 0;
  function start(scope) {
    scope = scope || document;
    scope.querySelectorAll(".asta-panel.asta-theories").forEach(function (root) {
      if (root.hasAttribute("data-asta-drawn")) return;
      var scripts = [], testsEl = null;
      for (var n = root.nextElementSibling; n && /^script$/i.test(n.tagName); n = n.nextElementSibling) {
        if (n.classList.contains("asta-theories-data")) scripts.push(n);
        else if (n.classList.contains("asta-theories-tests")) testsEl = n;
      }
      if (!scripts.length && !drawn) {
        scripts = Array.prototype.slice.call(document.querySelectorAll("script.asta-theories-data"));
        if (!scripts.length) {
          var one = document.getElementById("asta-theories-data");
          if (one) scripts = [one];
        }
        testsEl = document.querySelector("script.asta-theories-tests");
      }
      if (!scripts.length) return;
      root.setAttribute("data-asta-drawn", "");
      if (!root.id && drawn) root.id = "asta-theories-" + (drawn + 1); // its query tabs' ids
      drawn++;
      draw(root, scripts, testsEl);
    });
  }
  function draw(root, scripts, testsEl) {
    var names = [];
    try { names = JSON.parse(root.getAttribute("data-asta-names") || "[]"); } catch (e) { names = []; }
    var tests = null;
    try { tests = testsEl ? (JSON.parse(testsEl.textContent).tests || []) : null; } catch (e) { tests = null; }
    if (tests && !Array.isArray(tests)) tests = [];
    safeRender(root, function () {
      return scripts.map(function (s) { return JSON.parse(s.textContent); });
    }, {
      sources: scripts.map(function (s) { return s.getAttribute("data-asta-source") || ""; }),
      names: names,
      papers: root.getAttribute("data-asta-papers") || "",
      tests: tests
    });
  }
  window.AstaPages.widgets = window.AstaPages.widgets || [];
  window.AstaPages.widgets.push({ name: "theories", order: 1, start: start });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { start(document); });
  else start(document);
})();
