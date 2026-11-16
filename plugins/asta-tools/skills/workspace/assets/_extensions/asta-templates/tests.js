/* asta-templates tests: a run's tests, one row per test folder, read-only.
   Reads the JSON the asta-tests shortcode embedded (script.asta-tests-data, one per panel: each
   test's index entry, the fields of its result_summary.json the table shows, and links to its
   files, which asta-templates.lua found on disk) and draws a sortable, filterable table: test, what
   it tests, verdict, effect, p, animals and links; a row opens to its direction, the full effect,
   its figures and its files. theories.js uses the same verdicts and test cards for a theory's
   Tests tab (window.AstaTemplates.testsLib).
   Verdict: the summary's `verdict` if it has one; else ran: false is "not run"; meets_threshold
   true is "met", false "not met", an object of per-region booleans "met in X of Y"; anything
   else "undecided". A folder with no summary yet is "running"; an index entry with no folder
   is "not started". Anchors: #test-<id> opens that test's row. Uses no browser storage and
   makes no request: links and figures point at the files on disk. */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  function arr(x) { return Array.isArray(x) ? x : []; }
  // The address as this panel's page sees it: asta-templates.js knows which page of a flow's feed
  // the panel came from (null when the address is another page's); without it, the page's own.
  function hashOf(el) { var A = window.AstaTemplates; return A && A.hashOf ? A.hashOf(el) : location.hash; }
  function isNum(v) { return typeof v === "number" && isFinite(v); }
  function minus(s) { return String(s).replace(/^-/, "−"); }
  var CHEVRON = '<svg class="ap-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var SORT = '<svg class="af-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5l-6 6h4v8h4v-8h4z"/></svg>';

  // Numbers as a reader scans them: three significant digits, very small ones in exponent form.
  function fmtNum(v) {
    if (!isNum(v)) return String(v);
    if (v === 0) return "0";
    var a = Math.abs(v);
    if (Number.isInteger(v) && a < 1e6) return minus(v);
    if (a < 1e-3 || a >= 1e6) return minus(v.toExponential(1));
    return minus(String(Number(v.toPrecision(3))));
  }
  function fmtP(v) {
    if (!isNum(v)) return String(v);
    if (v < 0.001) return "<0.001";
    return String(Number(v.toPrecision(2)));
  }
  // The leaves of a nested value, as [path, value] pairs; a short list of plain values (a
  // confidence interval) is one leaf.
  function leaves(v, path, out) {
    out = out || [];
    if (out.length >= 60) return out;
    if (Array.isArray(v) && v.length && v.length <= 6 && v.every(function (x) { return x == null || typeof x !== "object"; })) out.push([path, v]);
    else if (v && typeof v === "object") {
      if (Array.isArray(v)) v.forEach(function (x, i) { leaves(x, path ? path + "[" + i + "]" : "[" + i + "]", out); });
      else Object.keys(v).forEach(function (k) { leaves(v[k], path ? path + "." + k : k, out); });
    } else if (v != null) out.push([path, v]);
    return out;
  }
  function label(path) { return String(path || "").replace(/\[\d+\]/g, "").split(".").filter(Boolean).join(" "); }
  function scalar(v, fmt) {
    if (Array.isArray(v)) return "[" + v.map(function (x) { return x == null ? "—" : scalar(x, fmt); }).join(", ") + "]";
    if (isNum(v)) return fmt(v);
    if (typeof v === "boolean") return v ? "yes" : "no";
    return String(v);
  }
  // A p or an animal count that is an object (one per region): its range, the rest in the tooltip.
  function range(v, fmt) {
    var c = compact(v, fmt);
    if (!v || typeof v !== "object") return c;
    // For p, only values a p can take (a summary's p object may carry its test statistic too).
    var nums = leaves(v).filter(function (x) { return isNum(x[1]) && (fmt !== fmtP || (x[1] >= 0 && x[1] <= 1)); }).map(function (x) { return x[1]; });
    if (!nums.length) return c;
    var lo = Math.min.apply(null, nums), hi = Math.max.apply(null, nums);
    return { text: lo === hi ? fmt(lo) : fmt(lo) + "–" + fmt(hi), title: c.title, num: lo };
  }
  // A value in a table cell: a number as it is; an object as its first two numbers, the rest in
  // the tooltip. Returns {text, title, num} (num: the value to sort by).
  function compact(v, fmt) {
    fmt = fmt || fmtNum;
    if (v == null || v === "") return { text: "—", title: "", num: null };
    if (isNum(v)) return { text: fmt(v), title: "", num: v };
    if (typeof v !== "object") {
      var s = scalar(v, fmt);
      return { text: s.length > 40 ? s.slice(0, 38) + "…" : s, title: s.length > 40 ? s : "", num: null };
    }
    var all = leaves(v), nums = all.filter(function (x) { return isNum(x[1]); });
    // Named quantities before list items and per-animal values (keys that are numbers).
    var named = nums.filter(function (x) { return !/\[\d+\]/.test(x[0]) && !/(^|\.)\d+(\.|$)/.test(x[0]); });
    var shown = named.length ? named : nums.length ? nums : all;
    if (!shown.length) return { text: "—", title: "", num: null };
    var text = shown.slice(0, 2).map(function (x) { return (label(x[0]) ? label(x[0]) + " " : "") + scalar(x[1], fmt); }).join(" · ");
    if (shown.length > 2) text += " +" + (shown.length - 2);
    return { text: text, title: all.map(function (x) { return x[0] + ": " + scalar(x[1], fmt); }).join("\n"), num: shown.length && isNum(shown[0][1]) ? shown[0][1] : null };
  }

  // ---- verdicts -------------------------------------------------------------------------------

  var RANK = { met: 0, partial: 1, notmet: 2, other: 3, undecided: 4, running: 5, notrun: 6, notstarted: 7 };
  var KEY_LABEL = { met: "met", partial: "partly met", notmet: "not met", other: "other", undecided: "undecided",
    running: "running", notrun: "not run", notstarted: "not started" };
  // An explicit verdict's words, sorted into the table's kinds (the words are shown as written).
  function classify(text) {
    var t = String(text).toLowerCase();
    if (/\b(not met|reject|falsif|opposite|not supported|refut|fail)/.test(t)) return "notmet";
    if (/\b(partly|partial|mixed)/.test(t)) return "partial";
    if (/\b(undecided|underpowered|not decided|inconclusive|not identifiable|no data)/.test(t)) return "undecided";
    if (/\b(not run|skipped|not runnable)/.test(t)) return "notrun";
    if (/\b(running|pending|in progress)/.test(t)) return "running";
    if (/\b(met|support|replicat|confirm|pass)/.test(t)) return "met";
    return "other";
  }
  function verdict(t) {
    if (t.missing) return { key: "notstarted", label: "not started", note: "The index lists this test; it has no folder yet." };
    var s = t.summary;
    if (!s) {
      if (t.summaryHref) return { key: "undecided", label: "undecided", note: (t.summaryName || "The summary") + " holds no summary fields." };
      if (t.result) return { key: "undecided", label: "undecided", note: "result.md, but no result_summary.json." };
      return { key: "running", label: "running", note: "No result yet: the folder has no result_summary.json." };
    }
    if (typeof s.verdict === "string" && s.verdict.trim()) return { key: classify(s.verdict), label: s.verdict.trim(), note: s.status || "" };
    if (s.ran === false || s.runnable === false) return { key: "notrun", label: "not run", note: typeof s.status === "string" ? s.status : "" };
    var mt = s.meets_threshold;
    if (mt === true) return { key: "met", label: "met", note: "" };
    if (mt === false) return { key: "notmet", label: "not met", note: "" };
    if (mt && typeof mt === "object" && !Array.isArray(mt)) {
      var parts = Object.keys(mt).filter(function (k) { return typeof mt[k] === "boolean"; });
      if (parts.length) {
        var yes = parts.filter(function (k) { return mt[k]; });
        return {
          key: yes.length === parts.length ? "met" : yes.length ? "partial" : "notmet",
          label: "met in " + yes.length + " of " + parts.length,
          parts: parts.map(function (k) { return [k, mt[k]]; }),
          note: typeof mt.rule === "string" ? mt.rule : ""
        };
      }
    }
    return { key: "undecided", label: "undecided", note: typeof s.status === "string" ? s.status : "" };
  }
  function verdictChip(v) {
    return '<span class="ap-chip ap-v ap-v-' + v.key + '" title="' + esc(v.note || "") + '">' + esc(v.label) + "</span>";
  }
  function partsLine(v) {
    if (!v.parts) return "";
    return '<div class="ap-ts-parts">' + v.parts.map(function (p) {
      return '<span class="' + (p[1] ? "ap-ts-yes" : "ap-ts-no") + '">' + esc(p[0]) + (p[1] ? " ✓" : " ✗") + "</span>";
    }).join(" ") + "</div>";
  }

  // ---- what a test measured --------------------------------------------------------------------

  // The summary's own effect, p and animals; a summary with several subject-level tests and no
  // single effect gives its first test that has a p.
  function numbers(t) {
    var s = t.summary || {}, sub = arr(s.subject_level_tests), pick = null, more = 0;
    var effect = s.effect, p = s.p, name = s.effect_name || s.effect_label || s.effect_description || "";
    if (effect == null && p == null && sub.length) {
      var withP = sub.filter(function (x) { return x && isNum(x.p); });
      pick = withP[0] || sub[0];
      more = sub.length - 1;
      effect = pick.effect; p = pick.p; name = pick.name || "";
    }
    var n = s.n_animals != null ? s.n_animals : s.n_mice != null ? s.n_mice : s.n_subjects;
    if (n == null && sub.length) {
      var ns = sub.map(function (x) { return x && (isNum(x.n_mice) ? x.n_mice : x.n_animals); }).filter(isNum);
      if (ns.length) n = Math.max.apply(null, ns);
    }
    return { effect: compact(effect), p: range(p, fmtP), n: range(n, fmtNum), name: typeof name === "string" ? name : "",
      units: typeof s.effect_units === "string" ? s.effect_units : "", more: more, direction: typeof s.direction === "string" ? s.direction : s.direction && typeof s.direction === "object" ?
        leaves(s.direction).map(function (x) { return label(x[0]) + " " + scalar(x[1], fmtNum); }).join(" · ") : "" };
  }
  function what(t) {
    var ix = t.index || {};
    var main = ix.theory_name || ix.title || ix.name || ix.hypothesis || ix.question || t.hypothesis || t.heading || "";
    var tags = [ix.kind, ix.dataset].filter(function (x) { return typeof x === "string" && x; }).concat(arr(ix.labels));
    return { text: String(main), tags: tags, title: t.heading || "" };
  }
  function links(t) {
    var out = [];
    if (t.design) out.push(["design.md", t.design]);
    if (t.code) out.push([t.codeName || "code", t.code]);
    if (t.result) out.push(["result.md", t.result]);
    if (t.summaryHref) out.push([t.summaryName || "summary", t.summaryHref]);
    return out;
  }
  // short: "design · code · result · summary", for the table's narrow Files column.
  function linksHtml(t, withFolder, short) {
    var l = links(t).map(function (x) {
      var name = !short ? x[0] : x[1] === t.summaryHref ? "summary" : x[1] === t.code ? "code" : x[0].replace(/\.md$/, "");
      return '<a href="' + esc(x[1]) + '" title="' + esc(x[0]) + '">' + esc(name) + "</a>";
    });
    if (withFolder && t.href && !t.missing) l.push('<a href="' + esc(t.href) + '" title="The test\'s folder">' + esc(t.id) + "/</a>");
    return l.join('<span class="ap-muted"> · </span>');
  }
  function figuresHtml(t) {
    var figs = arr(t.figures);
    if (!figs.length) return "";
    // f.href opens the workspace's file; f.src is the copy in the site that the page shows (none
    // for a figure too large to copy: a link to the file stands in for it).
    return '<div class="ap-ts-figs">' + figs.map(function (f) {
      var src = f.src || (f.size ? "" : f.href);
      if (!src) {
        return '<a class="ap-ts-fig ap-ts-fig-big" href="' + esc(f.href) + '" title="' + esc(f.name) + '"><span class="ap-ts-fig-note">' +
          esc(f.size) + ", too large to show here</span><span>" + esc(f.name) + "</span></a>";
      }
      return '<a class="ap-ts-fig" href="' + esc(f.href) + '" title="' + esc(f.name) + '"><img src="' + esc(src) +
        '" alt="' + esc(f.name) + '" loading="lazy"><span>' + esc(f.name) + "</span></a>";
    }).join("") + "</div>";
  }
  function leavesList(label, v, fmt) {
    if (!v || typeof v !== "object") return "";
    var all = leaves(v);
    if (all.length < 2) return "";
    return '<div class="ap-ts-leaves"><div class="ap-label">' + esc(label) + "</div><dl>" + all.slice(0, 40).map(function (x) {
      // A number or a short list sits at the right of its name; words get a line of their own.
      var text = typeof x[1] === "string" && x[1].length > 24;
      return "<div" + (text ? ' class="ap-ts-text"' : "") + "><dt>" + esc(x[0]) + "</dt><dd>" + esc(scalar(x[1], fmt)) + "</dd></div>";
    }).join("") + "</dl></div>";
  }
  // A test as a card: for an opened row, and for a theory's Tests tab (opts.head: id, verdict and
  // tags on top).
  function card(t, opts) {
    opts = opts || {};
    var v = verdict(t), n = numbers(t), w = what(t), s = t.summary || {};
    var head = opts.head ? '<div class="ap-ts-card-head"><strong class="ap-ts-id">' + esc(t.id) + "</strong>" + verdictChip(v) +
      w.tags.map(function (x) { return '<span class="ap-chip">' + esc(x) + "</span>"; }).join("") + "</div>" +
      (opts.what && w.text ? '<p class="ap-ts-what-full">' + esc(w.text) + "</p>" : "") : "";
    var facts = [];
    // An effect or p that is an object is listed in full below; the facts give the single ones.
    var bigEffect = leaves(s.effect).length > 1, bigP = leaves(s.p).length > 1;
    if (n.effect.text !== "—" && !bigEffect) facts.push(["Effect", esc(n.effect.text) + (n.units ? ' <span class="ap-muted">' + esc(n.units) + "</span>" : "") + (n.name ? '<div class="ap-muted">' + esc(n.name) + "</div>" : "")]);
    else if (n.name) facts.push(["Effect", esc(n.name)]);
    if (n.p.text !== "—" && !bigP) facts.push(["p", esc(n.p.text)]);
    if (n.n.text !== "—") facts.push(["Animals", esc(n.n.text)]);
    if (n.direction) facts.push(["Direction", esc(n.direction)]);
    if (v.parts) facts.push(["Threshold", partsLine(v) + (v.note ? '<div class="ap-muted">' + esc(v.note) + "</div>" : "")]);
    else if (v.note) facts.push(["Status", esc(v.note)]);
    var sub = arr(s.subject_level_tests);
    var subHtml = sub.length ? '<div class="ap-ts-sub"><div class="ap-label">Subject-level tests</div><table><thead><tr><th>Test</th><th>n</th><th>Effect</th><th>p</th></tr></thead><tbody>' +
      sub.map(function (x) {
        return "<tr><td>" + esc(x.name || "") + "</td><td>" + esc(compact(isNum(x.n_mice) ? x.n_mice : x.n_animals).text) + "</td><td>" + esc(compact(x.effect).text) +
          "</td><td>" + esc(compact(x.p, fmtP).text) + "</td></tr>";
      }).join("") + "</tbody></table></div>" : "";
    var l = linksHtml(t, true);
    return '<div class="ap-ts-card">' + head +
      (facts.length ? '<dl class="ap-ts-facts">' + facts.map(function (f) { return "<div><dt>" + f[0] + "</dt><dd>" + f[1] + "</dd></div>"; }).join("") + "</dl>" : "") +
      leavesList("Effect, in full", s.effect, fmtNum) + leavesList("p, in full", s.p, fmtP) + leavesList("Animals, in full", s.n_animals, fmtNum) + subHtml +
      (l ? '<div class="ap-ts-links"><span class="ap-files-label">Files</span> ' + l + "</div>" : "") +
      figuresHtml(t) + "</div>";
  }
  // "1 of 2 met" for a theory's tests.
  function tally(tests) {
    var c = {};
    tests.forEach(function (t) { var k = verdict(t).key; c[k] = (c[k] || 0) + 1; });
    var text = (c.met || 0) + " of " + tests.length + " met";
    if (c.partial) text += ", " + c.partial + " partly";
    var key = c.met ? "met" : c.partial ? "partial" : c.notmet ? "notmet" : c.running ? "running" : "undecided";
    return { text: text, key: key, counts: c };
  }

  window.AstaTemplates = window.AstaTemplates || {};
  window.AstaTemplates.testsLib = { verdict: verdict, verdictChip: verdictChip, card: card, tally: tally, numbers: numbers, what: what, fmtNum: fmtNum, fmtP: fmtP };

  // ---- the asta-tests panel ------------------------------------------------------------------

  function idKey(s) { return String(s).toLowerCase().replace(/\d+/g, function (d) { return ("000000000000" + d).slice(-12); }); }
  var COLS = [
    ["id", "Test", "ap-ts-c-id"], ["what", "What it tests", "ap-ts-c-what"], ["verdict", "Verdict", "ap-ts-c-verdict"],
    ["effect", "Effect", "ap-ts-c-effect"], ["p", "p", "ap-ts-c-num"], ["n", "n", "ap-ts-c-num ap-ts-c-n"], ["files", "Files", "ap-ts-c-files"]
  ];

  function render(root, data) {
    var tests = arr(data.tests).filter(function (t) { return t && t.id != null; });
    var others = arr(data.others);
    var rows = tests.map(function (t, i) {
      var v = verdict(t), n = numbers(t), w = what(t);
      return { t: t, i: i, v: v, n: n, w: w, anchor: "test-" + String(t.id).replace(/[^A-Za-z0-9_.-]+/g, "-"),
        hay: [t.id, w.text, w.tags.join(" "), v.label, n.name, n.direction].join(" ").toLowerCase() };
    });
    var state = { text: "", only: null, sort: { field: null, dir: 1 }, open: {} };
    var counts = {};
    rows.forEach(function (r) { counts[r.v.key] = (counts[r.v.key] || 0) + 1; });
    var kinds = Object.keys(counts).sort(function (a, b) { return RANK[a] - RANK[b]; });
    var title = root.getAttribute("data-asta-title") || plural(tests.length, "test", "tests");

    root.innerHTML = '<div class="ap-tt ap-ts">' +
      '<div class="ap-ad-exps-head"><button type="button" class="ap-tt-head" aria-expanded="true">' + CHEVRON + "<h2>" + esc(title) + "</h2></button>" +
      (tests.length > 1 ? '<input type="search" class="ap-ad-search" placeholder="Filter tests" aria-label="Filter tests">' : "") + "</div>" +
      (kinds.length > 1 ? '<div class="ap-ts-filters" role="group" aria-label="Show tests by verdict">' +
        '<button type="button" class="ap-ts-filter" data-only="" aria-pressed="true">All <span class="ap-n">' + tests.length + "</span></button>" +
        kinds.map(function (k) {
          return '<button type="button" class="ap-ts-filter" data-only="' + k + '" aria-pressed="false"><span class="ap-ts-dot ap-v-' + k + '"></span>' +
            esc(KEY_LABEL[k]) + ' <span class="ap-n">' + counts[k] + "</span></button>";
        }).join("") + "</div>" : "") +
      '<div class="ap-tt-wrap ap-ts-scroll"><table class="ap-ts-table"><thead><tr>' + COLS.map(function (c) {
        return '<th class="' + c[2] + '"' + (c[0] === "files" ? "" : ' aria-sort="none"') + ">" + (c[0] === "files" ? '<span class="ap-ts-th">' + c[1] + "</span>" :
          '<button type="button" data-sort="' + c[0] + '">' + esc(c[1]) + '<span class="ap-ad-sort" aria-hidden="true">' + SORT + "</span></button>") + "</th>";
      }).join("") + "</tr></thead><tbody></tbody></table></div>" +
      '<p class="ap-legend">One row per test folder; open a row for its direction, figures and files. The verdict is read from the test\'s result_summary.json: ' +
      "its verdict if it states one, else whether it met its committed threshold. A folder with no summary yet is running.</p>" +
      (others.length ? '<p class="ap-legend ap-ts-others"><span class="ap-files-label">Also in this folder</span> ' + others.map(function (o) {
        return '<a href="' + esc(o.href) + '">' + esc(o.name) + "</a>" + (o.size ? ' <span class="ap-muted">' + esc(o.size) + "</span>" : "");
      }).join('<span class="ap-muted"> · </span>') + "</p>" : "") + "</div>";

    var tt = root.querySelector(".ap-ts"), tog = tt.querySelector(".ap-tt-head"), tbody = root.querySelector("tbody");
    tog.addEventListener("click", function () { var c = tt.classList.toggle("ap-collapsed"); tog.setAttribute("aria-expanded", String(!c)); });

    function sortValue(r, f) {
      if (f === "id") return idKey(r.t.id);
      if (f === "what") return r.w.text.toLowerCase();
      if (f === "verdict") return RANK[r.v.key] * 1000 + (r.v.parts ? r.v.parts.length - r.v.parts.filter(function (p) { return p[1]; }).length : 0);
      if (f === "effect") return r.n.effect.num;
      if (f === "p") return r.n.p.num;
      if (f === "n") return r.n.n.num;
      return null;
    }
    function shown() {
      var list = rows.filter(function (r) {
        return (!state.only || r.v.key === state.only) && (!state.text || r.hay.indexOf(state.text) >= 0);
      });
      var f = state.sort.field, dir = state.sort.dir;
      if (f) {
        list.sort(function (a, b) {
          var x = sortValue(a, f), y = sortValue(b, f);
          if (x == null && y == null) return a.i - b.i;
          if (x == null) return 1;
          if (y == null) return -1;
          var c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
          return c * dir || a.i - b.i;
        });
      }
      return list;
    }
    function rowHtml(r) {
      var t = r.t, open = !!state.open[r.i];
      var effect = r.n.effect.text === "—" ? '<span class="ap-muted">—</span>' : '<div class="ap-ts-effect" title="' + esc(r.n.effect.title) + '">' + esc(r.n.effect.text) + "</div>" +
        (r.n.name ? '<div class="ap-ts-sub-line" title="' + esc(r.n.name) + '">' + esc(r.n.name) + "</div>" : "") +
        (r.n.more ? '<div class="ap-ts-sub-line">+' + plural(r.n.more, "more test", "more tests") + "</div>" : "");
      var files = linksHtml(t, false, true) || (t.missing ? '<span class="ap-muted">no folder</span>' : "");
      var nfig = arr(t.figures).length;
      if (nfig) files += (files ? '<span class="ap-muted"> · </span>' : "") + '<span class="ap-muted">' + plural(nfig, "figure", "figures") + "</span>";
      return '<tr class="ap-ts-row' + (open ? " ap-open" : "") + '" id="' + esc(r.anchor) + '" data-i="' + r.i + '" tabindex="0" aria-expanded="' + open + '">' +
        '<td class="ap-ts-c-id"><span class="ap-ts-idcell">' + CHEVRON + "<strong>" + esc(t.id) + "</strong></span></td>" +
        '<td class="ap-ts-c-what"><div class="ap-ts-what" title="' + esc(r.w.title || r.w.text) + '">' + esc(r.w.text || "—") + "</div>" +
        (r.w.tags.length ? '<div class="ap-ts-tags">' + r.w.tags.map(function (x) { return '<span class="ap-chip">' + esc(x) + "</span>"; }).join("") + "</div>" : "") + "</td>" +
        '<td class="ap-ts-c-verdict">' + verdictChip(r.v) + partsLine(r.v) + "</td>" +
        '<td class="ap-ts-c-effect">' + effect + "</td>" +
        '<td class="ap-ts-c-num" title="' + esc(r.n.p.title) + '">' + esc(r.n.p.text) + "</td>" +
        '<td class="ap-ts-c-num ap-ts-c-n" title="' + esc(r.n.n.title) + '">' + esc(r.n.n.text) + "</td>" +
        '<td class="ap-ts-c-files">' + files + "</td></tr>" +
        (open ? '<tr class="ap-ts-detail"><td colspan="' + COLS.length + '">' + card(t) + "</td></tr>" : "");
    }
    function draw() {
      var list = shown();
      root.querySelectorAll("[data-sort]").forEach(function (b) {
        var on = b.getAttribute("data-sort") === state.sort.field;
        b.classList.toggle("ap-ad-sorted", on); b.classList.toggle("ap-ad-desc", on && state.sort.dir < 0);
        b.parentNode.setAttribute("aria-sort", on ? (state.sort.dir < 0 ? "descending" : "ascending") : "none");
      });
      root.querySelectorAll(".ap-ts-filter").forEach(function (b) {
        b.setAttribute("aria-pressed", String((b.getAttribute("data-only") || null) === state.only));
      });
      tbody.innerHTML = list.map(rowHtml).join("") ||
        '<tr><td colspan="' + COLS.length + '" class="ap-ad-none">' + (rows.length ? "No test matches the filter." : "No tests yet.") + "</td></tr>";
    }
    function toggle(i) { state.open[i] = !state.open[i]; draw(); }

    var input = root.querySelector(".ap-ad-search");
    if (input) input.addEventListener("input", function () { state.text = input.value.trim().toLowerCase(); draw(); });
    root.querySelectorAll(".ap-ts-filter").forEach(function (b) {
      b.addEventListener("click", function () { state.only = b.getAttribute("data-only") || null; draw(); });
    });
    root.querySelectorAll("[data-sort]").forEach(function (b) {
      b.addEventListener("click", function () {
        var f = b.getAttribute("data-sort");
        if (state.sort.field !== f) state.sort = { field: f, dir: 1 };
        else if (state.sort.dir === 1) state.sort = { field: f, dir: -1 };
        else state.sort = { field: null, dir: 1 };
        draw();
      });
    });
    tbody.addEventListener("click", function (ev) {
      if (ev.target.closest && ev.target.closest("a")) return;
      var tr = ev.target.closest && ev.target.closest("tr.ap-ts-row");
      if (tr) toggle(+tr.getAttribute("data-i"));
    });
    tbody.addEventListener("keydown", function (ev) {
      var tr = ev.target.closest && ev.target.closest("tr.ap-ts-row");
      if (tr && ev.target === tr && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); toggle(+tr.getAttribute("data-i")); }
    });
    draw();

    // #test-<id>: open that row and bring it into view (clearing a filter that hides it).
    function fromHash() {
      var h = hashOf(root);
      if (h == null) return;
      try { h = decodeURIComponent(h.slice(1)); } catch (e) { h = ""; }
      var r = rows.filter(function (x) { return x.anchor === h; })[0];
      if (!r) return;
      state.only = null; state.text = ""; if (input) input.value = "";
      state.open[r.i] = true;
      draw();
      var el = root.querySelector('[id="' + r.anchor + '"]');
      if (el && el.scrollIntoView) el.scrollIntoView({ block: "center" });
    }
    window.addEventListener("hashchange", fromHash);
    fromHash();
  }

  function safeRender(root, readData) {
    try {
      render(root, readData());
    } catch (e) {
      root.innerHTML = '<div class="ap-error">The tests could not be read (' + esc(e.message) + "). Render the page again.</div>";
    }
  }
  window.AstaTemplates.tests = safeRender;

  // Each asta-tests panel in scope draws itself, once, from its own data (data-asta-data names
  // it; the script follows the panel). asta-templates.js calls start on a page appended to a flow's
  // feed, so a document can hold several pages' panels.
  function start(scope) {
    scope = scope || document;
    scope.querySelectorAll(".asta-panel.asta-tests").forEach(function (root) {
      if (root.hasAttribute("data-asta-drawn")) return;
      var id = root.getAttribute("data-asta-data") || "", src = root.nextElementSibling;
      if (!src || src.id !== id) src = id ? document.getElementById(id) : null;
      if (!src) return;
      root.setAttribute("data-asta-drawn", "");
      safeRender(root, function () { return JSON.parse(src.textContent); });
    });
  }
  window.AstaTemplates.widgets = window.AstaTemplates.widgets || [];
  window.AstaTemplates.widgets.push({ name: "tests", order: 0, start: start });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { start(document); });
  else start(document);
})();
