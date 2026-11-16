/* asta-templates AutoDiscovery page: a run as autodiscovery.allen.ai's run view shows it, read-only,
   drawn in the theory and paper pages' style and the site's light and dark colours.
   Reads the JSON the asta-autods shortcode embedded (#asta-autods-data: each run's own files,
   as asta-templates.lua found them) and draws the run's header (status, links, Session
   configuration), its search tree (ExperimentGraph), its experiments table (ExperimentsTable:
   sortable, filterable) and the selected experiment (ExperimentDetails): belief shift,
   analysis, figures, review, then its plan and its code in their own tabs. Several runs on one
   page are listed first, like the theories.
   Files: `asta autodiscovery results` JSON ({run, experiments}) or the hosted Download → JSON
   draw everything; a local run's mcts_node records everything but the session settings; the
   hosted Download → CSV has no tree, code or figures. A run folder is run.md beside those.
   The run's header links its folder (and a local run's args.json); an experiment from a local
   run links its mcts_node_*.json and the run's rich_outputs/ folder, as asta-templates.lua found them.
   Anchors: #experiment-<id> opens an experiment (#run-<n>/experiment-<id> with several runs);
   a local run's node id does too: #node-3-1 or #node_3_1 (#run-<n>/node-3-1).
   Uses no browser storage and makes no request: every figure is in the page. */
(function () {
  "use strict";

  // The address as this panel's page sees it: asta-templates.js knows which page of a flow's feed
  // the panel came from (null when the address is another page's); without it, the page's own.
  function hashOf(el) { var A = window.AstaTemplates; return A && A.hashOf ? A.hashOf(el) : location.hash; }
  function urlOf(el, hash) { var A = window.AstaTemplates; return A && A.urlOf ? A.urlOf(el, hash) : hash; }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  // The service's experiment list writes every value as text ("None", "True", "0.75").
  function val(v) {
    if (v === "None" || v === "null" || v === "") return null;
    if (v === "True") return true;
    if (v === "False") return false;
    return v;
  }
  function num(v) { v = val(v); if (v == null || typeof v === "boolean") return null; var n = Number(v); return isFinite(n) ? n : null; }
  function str(v) { v = val(v); return v == null ? "" : String(v); }
  function obj(v) { v = val(v); return v && typeof v === "object" ? v : null; }

  // ---- icons (MUI's paths, as the hosted page draws them) ---------------------------------
  function icon(d, cls) { return '<svg class="af-icon' + (cls ? " " + cls : "") + '" viewBox="0 0 24 24" aria-hidden="true"><path d="' + d + '"/></svg>'; }
  var I = {
    close: "M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
    settings: "M19.43 12.98c.04-.32.07-.64.07-.98 0-.34-.03-.66-.07-.98l2.11-1.65c.19-.15.24-.42.12-.64l-2-3.46c-.09-.16-.26-.25-.44-.25-.06 0-.12.01-.17.03l-2.49 1c-.52-.4-1.08-.73-1.69-.98l-.38-2.65C14.46 2.18 14.25 2 14 2h-4c-.25 0-.46.18-.49.42l-.38 2.65c-.61.25-1.17.59-1.69.98l-2.49-1c-.06-.02-.12-.03-.18-.03-.17 0-.34.09-.43.25l-2 3.46c-.13.22-.07.49.12.64l2.11 1.65c-.04.32-.07.65-.07.98 0 .33.03.66.07.98l-2.11 1.65c-.19.15-.24.42-.12.64l2 3.46c.09.16.26.25.44.25.06 0 .12-.01.17-.03l2.49-1c.52.4 1.08.73 1.69.98l.38 2.65c.03.24.24.42.49.42h4c.25 0 .46-.18.49-.42l.38-2.65c.61-.25 1.17-.59 1.69-.98l2.49 1c.06.02.12.03.18.03.17 0 .34-.09.43-.25l2-3.46c.12-.22.07-.49-.12-.64zm-1.98-1.71c.04.31.05.52.05.73 0 .21-.02.43-.05.73l-.14 1.13.89.7 1.08.84-.7 1.21-1.27-.51-1.04-.42-.9.68c-.43.32-.84.56-1.25.73l-1.06.43-.16 1.13-.2 1.35h-1.4l-.19-1.35-.16-1.13-1.06-.43c-.43-.18-.83-.41-1.23-.71l-.91-.7-1.06.43-1.27.51-.7-1.21 1.08-.84.89-.7-.14-1.13c-.03-.31-.05-.54-.05-.74s.02-.43.05-.73l.14-1.13-.89-.7-1.08-.84.7-1.21 1.27.51 1.04.42.9-.68c.43-.32.84-.56 1.25-.73l1.06-.43.16-1.13.2-1.35h1.39l.19 1.35.16 1.13 1.06.43c.43.18.83.41 1.23.71l.91.7 1.06-.43 1.27-.51.7 1.21-1.07.85-.89.7.14 1.13zM12 8c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4zm0 6c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z",
    hourglass: "m18 22-.01-6L14 12l3.99-4.01L18 2H6v6l4 4-4 3.99V22h12zM8 7.5V4h8v3.5l-4 4-4-4z",
    search: "M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
    arrow: "m4 12 1.41 1.41L11 7.83V20h2V7.83l5.58 5.59L20 12l-8-8-8 8z",
    sep: "M11 19V5h2v14z",
    plus: "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z",
    minus: "M19 13H5v-2h14v2z",
    center: "M5 15H3v4c0 1.1.9 2 2 2h4v-2H5v-4zM5 5h4V3H5c-1.1 0-2 .9-2 2v4h2V5zm14-2h-4v2h4v4h2V5c0-1.1-.9-2-2-2zm0 16h-4v2h4c1.1 0 2-.9 2-2v-4h-2v4zM12 9c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z",
    split: "M3 15h8v-2H3v2zm0 4h8v-2H3v2zm0-8h8V9H3v2zm0-6v2h8V5H3zm10 0h8v14h-8V5z",
    open: "M21 11V3h-8l3.29 3.29-10 10L3 13v8h8l-3.29-3.29 10-10z",
    shrink: "M22 3.41 16.71 8.7 20 12h-8V4l3.29 3.29L20.59 2 22 3.41zM3.41 22l5.29-5.29L12 20v-8H4l3.29 3.29L2 20.59 3.41 22z",
    download: "M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z",
    more: "M16.59 8.59 12 13.17 7.41 8.59 6 10l6 6 6-6z"
  };

  // ---- reading the run files ------------------------------------------------------------

  // RFC 4180, as the hosted Download → CSV writes it (quoted fields with commas, "" and
  // newlines; a byte-order mark first).
  function parseCsv(text) {
    text = String(text || "").replace(/^﻿/, "");
    var rows = [], row = [], field = "", q = false, i = 0, c;
    for (; i < text.length; i++) {
      c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else q = false; }
        else field += c;
      } else if (c === '"') q = true;
      else if (c === ",") { row.push(field); field = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(field); field = "";
        if (row.length > 1 || row[0] !== "") rows.push(row);
        row = [];
      } else field += c;
    }
    row.push(field);
    if (row.length > 1 || row[0] !== "") rows.push(row);
    return rows;
  }

  // ExperimentUtils.ts
  function beliefLabel(score) {
    if (score == null) return "Uncertain";
    if (score > 0 && score < 0.25) return "Likely False";
    if (score >= 0.25 && score < 0.5) return "Maybe False";
    if (score === 0.5) return "Uncertain";
    if (score > 0.5 && score < 0.75) return "Maybe True";
    if (score >= 0.75 && score <= 1) return "Likely True";
    return "Uncertain";
  }
  function direction(s) { return s == null || s === 0 ? "Neutral" : s > 0 ? "Positive" : "Negative"; }
  // BeliefDistributionPlot.tsx: a categorical belief collapsed to a 0-1 mean.
  var SCORE = { definitely_false: 0, maybe_false: 0.25, uncertain: 0.5, maybe_true: 0.75, definitely_true: 1 };
  function beliefMean(b) {
    b = obj(b);
    if (!b) return null;
    var p = b.prior_params;
    if (!p || p.length < 2) return typeof b.mean === "number" ? b.mean : null;
    var a = Number(p[0]) || 0, be = Number(p[1]) || 0;
    Object.keys(SCORE).forEach(function (k) { var n = Number(b[k]) || 0; a += n * SCORE[k]; be += n * (1 - SCORE[k]); });
    return a > 0 && be > 0 ? a / (a + be) : null;
  }
  // A CSV keeps the label, not the number: the plot puts it mid-band.
  var LABEL_AT = { "likely false": 0.125, "maybe false": 0.375, "uncertain": 0.5, "maybe true": 0.625, "likely true": 0.875 };

  function experiment() {
    return { id: null, key: "", parent: null, status: "SUCCEEDED", hypothesis: "", analysis: "", analysisLabel: "Analysis",
      review: "", reviewLabel: "Review", plan: null, code: "", codeOutput: "", figures: [], surprise: null,
      isSurprising: null, prior: null, posterior: null, priorMean: null, posteriorMean: null, labels: null, extra: [], createdAt: null };
  }
  function finish(e, width) {
    e.key = e.key || "exp-" + e.id;
    if (e.status !== "SUCCEEDED") e.surprising = false;
    else if (width != null) e.surprising = Math.abs(e.surprise || 0) >= width;
    else e.surprising = !!e.isSurprising;
    return e;
  }

  // The hosted Download → CSV (exportUtils.ts). Its newer form calls the analysis and review
  // columns Findings and Validity Check; a table kept by hand may add columns of its own.
  var CSV_KNOWN = { id: 1, hypothesis: 1, surprisal: 1, "belief before": 1, "belief after": 1, direction: 1,
    objective: 1, steps: 1, deliverables: 1, analysis: 1, findings: 1, review: 1, "validity check": 1 };
  function fromCsv(text) {
    var rows = parseCsv(text);
    if (!rows.length) return [];
    var head = rows[0].map(function (h) { return h.trim(); });
    var low = head.map(function (h) { return h.toLowerCase(); });
    if (low.indexOf("hypothesis") < 0) throw new Error("the CSV has no Hypothesis column, so it is not an AutoDiscovery download");
    return rows.slice(1).map(function (r, k) {
      function get(name) { var i = low.indexOf(name); return i < 0 ? "" : (r[i] || "").trim(); }
      function label(a, b) { return low.indexOf(a) >= 0 ? head[low.indexOf(a)] : head[low.indexOf(b)]; }
      var e = experiment();
      e.id = num(get("id")); if (e.id == null) e.id = k + 1;
      e.hypothesis = get("hypothesis");
      var s = num(get("surprisal")), dir = get("direction");
      var pre = get("belief before"), post = get("belief after");
      if (s == null && !pre && !post) e.status = "INCONCLUSIVE";
      if (s != null) e.surprise = /^neg/i.test(dir) ? -s : s;
      e.labels = { prior: pre, posterior: post, direction: dir };
      e.priorMean = LABEL_AT[pre.toLowerCase()]; e.posteriorMean = LABEL_AT[post.toLowerCase()];
      e.prior = e.priorMean; e.posterior = e.posteriorMean;
      e.analysis = get("analysis") || get("findings"); e.analysisLabel = label("analysis", "findings") || "Analysis";
      e.review = get("review") || get("validity check"); e.reviewLabel = label("review", "validity check") || "Review";
      if (get("objective") || get("steps") || get("deliverables")) e.plan = { objective: get("objective"), steps: get("steps"), deliverables: get("deliverables") };
      head.forEach(function (h, i) { if (!CSV_KNOWN[low[i]] && (r[i] || "").trim()) e.extra.push([h, r[i].trim()]); });
      return finish(e, null);
    });
  }

  // `asta autodiscovery results` ({run, experiments}), the hosted Download → JSON (a list), or
  // the service's experiments ({experiments}).
  function fromJson(d) {
    var list = Array.isArray(d) ? d : (d && d.experiments) || [];
    var meta = d && d.run ? obj(d.run.metadata) || {} : {};
    var width = num(meta.surprisal_width);
    return list.map(function (x, k) {
      var e = experiment();
      e.id = num(x.id_in_run != null ? x.id_in_run : x.idInRun != null ? x.idInRun : x.id);
      if (e.id == null) e.id = k + 1;
      e.key = str(x.experiment_id || x.experimentId) || "exp-" + e.id;
      e.parent = str(x.parent_id || x.parentId) || null;
      e.status = (str(x.status) || "SUCCEEDED").toUpperCase();
      e.hypothesis = str(x.hypothesis);
      e.surprise = num(x.surprise != null ? x.surprise : x.surprisal);
      var flag = val(x.is_surprising != null ? x.is_surprising : x.isSurprising);
      e.isSurprising = flag == null ? null : !!flag;
      e.prior = num(x.prior); e.posterior = num(x.posterior);
      e.priorMean = beliefMean(x.prior_belief || x.priorBelief); e.posteriorMean = beliefMean(x.posterior_belief || x.posteriorBelief);
      e.analysis = str(x.analysis); e.review = str(x.review);
      e.plan = obj(x.experiment_plan || x.experimentPlan);
      e.code = str(x.code); e.codeOutput = str(x.code_output || x.codeOutput);
      var ro = val(x.rich_outputs || x.richOutputs);
      e.figures = Array.isArray(ro) ? ro : [];
      e.createdAt = str(x.created_at || x.createdAt) || null;
      return finish(e, width);
    });
  }

  // A local run's mcts_node records, as the service serves them (api/utils/experiments.py).
  function fromNodes(nodes) {
    return (nodes || []).slice().sort(function (a, b) { return (a.creation_idx || 0) - (b.creation_idx || 0); })
      .map(function (n) {
        var e = experiment();
        e.id = (n.creation_idx || 0) - 1;
        e.key = String(n.id || "");
        e.parent = n.parent_id || null;
        e.status = n.success == null ? "PENDING" : n.success ? "SUCCEEDED" : "FAILED";
        e.isSurprising = n.surprising == null ? null : !!n.surprising;
        e.surprise = num(n.normalized_surprisal);
        e.priorMean = beliefMean(n.prior); e.posteriorMean = beliefMean(n.posterior);
        e.prior = e.priorMean; e.posterior = e.posteriorMean;
        e.hypothesis = n.hypothesis || ""; e.analysis = n.analysis || ""; e.review = n.review || "";
        e.plan = n.experiment_plan || null;
        e.code = n.code || ""; e.codeOutput = n.code_output || "";
        e.figures = n.figures || [];
        e.createdAt = n.created_at || null;
        e.file = n.file || ""; e.fileHref = n.href || "";
        return finish(e, null);
      });
  }

  // exportUtils.ts generateFilename: the download is named after the run.
  function slug(name) { return String(name || "").replace(/[^a-z0-9]/gi, "-").toLowerCase(); }
  function fileStem(source) { return String(source || "").split("/").pop().replace(/\.(csv|json)$/i, "").replace(/_\d{4}-\d{2}-\d{2}$/, "").replace(/\.results$/, ""); }
  function nameFromFile(source) {
    var s = fileStem(source).replace(/-{2,}/g, " – ").replace(/(\D)-|-(\D)/g, function (m, a, b) { return (a || "") + " " + (b || ""); })
      .replace(/\s+/g, " ").replace(/(\w) s\b/g, "$1's").trim();
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // run.md: the front matter's plain `key: value` lines and the "## Prompt" section.
  function parseRunMd(text) {
    var out = {}, m = /^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$/.exec(String(text || ""));
    if (!m) return out;
    m[1].split("\n").forEach(function (line) {
      var kv = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line);
      if (kv) out[kv[1]] = kv[2].trim().replace(/^"(.*)"$/, "$1").replace(/^'(.*)'$/, "$1");
    });
    var p = /(?:^|\n)##\s+Prompt\s*\n([\s\S]*?)(?=\n##\s|$)/.exec(m[2]);
    if (p) out.prompt = p[1].trim();
    return out;
  }

  function loadRun(raw) {
    var run = { source: raw.source || "", kind: raw.kind, skipped: raw.skipped || 0, info: null, meta: {}, details: {}, hrefs: obj(raw.hrefs) || {} };
    if (raw.kind === "folder") {
      run.record = parseRunMd(raw.runmd);
      run.csvHref = raw.csvHref || raw.csvSource || null;
      var res = raw.results;
      if (res) {
        var d = res.data != null ? res.data : JSON.parse(res.text);
        if (d && d.run) { run.info = d.run; run.meta = obj(d.run.metadata) || {}; run.details = obj(d.run.details) || {}; }
        run.experiments = fromJson(d);
        run.kind = "json";
        // The table kept beside the results may add reviews of its own: shown under their names.
        if (raw.csv) {
          var byId = {};
          fromCsv(raw.csv).forEach(function (c) { byId[c.id] = c; });
          run.experiments.forEach(function (e) { var c = byId[e.id]; if (c) e.extra = e.extra.concat(c.extra); });
        }
      } else if (raw.nodes) { run.experiments = fromNodes(raw.nodes); run.kind = "nodes"; run.meta = obj(raw.meta) || {}; }
      else { run.experiments = fromCsv(raw.csv || ""); run.kind = "csv"; }
    } else if (raw.kind === "nodes") { run.experiments = fromNodes(raw.nodes); run.meta = obj(raw.meta) || {}; }
    else if (raw.kind === "json") {
      var d = raw.data != null ? raw.data : JSON.parse(raw.text);
      if (d && d.run) { run.info = d.run; run.meta = obj(d.run.metadata) || {}; run.details = obj(d.run.details) || {}; }
      run.experiments = fromJson(d);
    } else run.experiments = fromCsv(raw.text);
    run.record = run.record || {};
    run.name = raw.name || run.record.name || (run.info && str(run.info.name)) || str(run.meta.name) || nameFromFile(run.source);
    run.title = run.record.title || "";
    run.label = run.record.label || "";
    run.link = run.record.link || "";
    run.status = (run.info && str(run.info.status)) || str(run.details.status) || "SUCCEEDED";
    run.requested = num(run.meta.n_experiments) || num(run.info && obj(run.info.stats) && obj(run.info.stats).requested_experiments) || run.experiments.length;
    run.byKey = {};
    run.experiments.forEach(function (e) { run.byKey[e.key] = e; });
    run.tree = run.experiments.some(function (e) { return e.parent; });
    return run;
  }

  // ---- text ------------------------------------------------------------------------------

  function inline(s) {
    return esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }
  // Markdown, enough of it for what AutoDiscovery writes: paragraphs, lists, bold, inline code.
  // A CSV runs a numbered list into one line ("1. a 2. b"); it is split back into items.
  function md(text) {
    if (Array.isArray(text)) text = text.map(function (x, i) { return (i + 1) + ". " + x; }).join("\n");
    text = String(text || "").trim();
    if (!text) return "";
    if (/^1\.\s/.test(text) && text.indexOf("\n") < 0 && /\s2\.\s/.test(text)) {
      text = text.split(/(?:^|\s)(?=\d+\.\s)/).map(function (x) { return x.trim(); }).filter(Boolean).join("\n");
    }
    return text.split(/\n\s*\n/).map(function (block) {
      var lines = block.split("\n").filter(function (l) { return l.trim(); });
      if (lines.length && lines.every(function (l) { return /^\s*[-*]\s+/.test(l); })) {
        return '<ul class="ap-list">' + lines.map(function (l) { return "<li>" + inline(l.replace(/^\s*[-*]\s+/, "")) + "</li>"; }).join("") + "</ul>";
      }
      if (lines.length && lines.every(function (l) { return /^\s*\d+[.)]\s+/.test(l); })) {
        return '<ol class="ap-list">' + lines.map(function (l) { return "<li>" + inline(l.replace(/^\s*\d+[.)]\s+/, "")) + "</li>"; }).join("") + "</ol>";
      }
      return "<p>" + lines.map(function (l) { return inline(l.replace(/^#+\s+/, "")); }).join("<br>") + "</p>";
    }).join("");
  }
  function section(label, body) {
    return body ? '<div class="ap-section"><div class="ap-label">' + esc(label) + "</div>" + body + "</div>" : "";
  }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  var CHEVRON = '<svg class="ap-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  function empty(title, hint) { return '<div class="ap-empty"><strong>' + esc(title) + "</strong>" + esc(hint || "") + "</div>"; }

  // CodeBlock: line numbers, folded after twenty lines.
  var FOLD = 20;
  function codeBlock(code) {
    var lines = String(code).replace(/\r\n/g, "\n").replace(/\n$/, "").split("\n");
    var fold = lines.length > FOLD;
    return '<div class="ap-ad-code' + (fold ? " ap-ad-folded" : "") + '"><pre><code>' + lines.map(function (l, i) {
      return '<span class="ap-ad-line' + (i >= FOLD ? " ap-ad-past" : "") + '"><span class="ap-ad-ln">' + (i + 1) + "</span>" + esc(l) + "</span>";
    }).join("") + "</code></pre>" + (fold ? '<button type="button" class="ap-ad-unfold">' + CHEVRON + "<span>Show all " + lines.length + " lines</span></button>" : "") + "</div>";
  }

  // RichOutputsSection.tsx: svg, then png, then jpeg, then text.
  function figure(b) {
    if (typeof b === "string") return { src: b };
    if (!b || typeof b !== "object") return null;
    if (b["image/svg+xml"]) {
      var t = String(b["image/svg+xml"]).trim();
      return { src: /^</.test(t) ? "data:image/svg+xml;utf8," + encodeURIComponent(t) : "data:image/svg+xml;base64," + t };
    }
    if (b["image/png"]) return { src: "data:image/png;base64," + b["image/png"] };
    if (b["image/jpeg"]) return { src: "data:image/jpeg;base64," + b["image/jpeg"] };
    if (b["text/plain"]) return { text: b["text/plain"] };
    return null;
  }

  // BeliefDistributionPlot.tsx: the two beliefs on the Likely False - Likely True axis.
  function beliefPlot(e) {
    var pre = e.priorMean, post = e.posteriorMean;
    if (pre == null && post == null) return "";
    var pp = pre != null ? pre * 100 : null, qp = post != null ? post * 100 : null;
    var arrow = pp != null && qp != null && Math.abs(pp - qp) > 0.5;
    function label(which, v, text) { return which + ": " + esc(text || beliefLabel(v)) + (e.labels ? "" : " (" + v.toFixed(3) + ")"); }
    return '<div class="ap-ad-belief' + (e.surprising ? " ap-ad-surprising" : "") + '" data-belief>' +
      '<div class="ap-ad-belief-labels">' +
      (qp != null ? '<span class="ap-ad-b-top ap-ad-b-post" data-pct="' + qp + '" style="left:' + qp + '%">' + label("Belief after", post, e.labels && e.labels.posterior) + "</span>" : "") +
      (pp != null ? '<span class="ap-ad-b-top ap-ad-b-pre" data-pct="' + pp + '" style="left:' + pp + '%">' + label("Belief before", pre, e.labels && e.labels.prior) + "</span>" : "") +
      '</div><div class="ap-ad-belief-axis">' +
      (arrow ? '<span class="ap-ad-b-arrow' + (qp < pp ? " ap-ad-b-left" : "") + '" style="left:' + Math.min(pp, qp) + "%;width:" + Math.abs(qp - pp) + '%"></span>' : "") +
      (pp != null ? '<span class="ap-ad-b-dot ap-ad-b-pre" style="left:' + pp + '%"></span>' : "") +
      (qp != null ? '<span class="ap-ad-b-dot ap-ad-b-post" style="left:' + qp + '%"></span>' : "") +
      '</div><div class="ap-ad-belief-ends"><span>Likely false</span><span>Likely true</span></div></div>';
  }
  // Push the two labels apart where they would overlap, and keep them inside the axis.
  function placeBeliefLabels(scope) {
    scope.querySelectorAll("[data-belief]").forEach(function (root) {
      var w = root.offsetWidth; if (!w) return;
      var items = [].slice.call(root.querySelectorAll(".ap-ad-b-top")).map(function (el) {
        return { el: el, dot: parseFloat(el.getAttribute("data-pct")) * w / 100, w: el.offsetWidth };
      }).sort(function (a, b) { return a.dot - b.dot; });
      items.forEach(function (it) { it.c = Math.max(it.w / 2, Math.min(w - it.w / 2, it.dot)); });
      if (items.length === 2) {
        var sep = (items[0].w + items[1].w) / 2 + 12;
        if (items[1].c - items[0].c < sep) {
          var mid = (items[0].dot + items[1].dot) / 2;
          items[0].c = Math.max(items[0].w / 2, mid - sep / 2);
          items[1].c = Math.min(w - items[1].w / 2, items[0].c + sep);
          items[0].c = Math.min(items[0].c, items[1].c - sep);
        }
      }
      items.forEach(function (it) { it.el.style.left = it.c + "px"; });
    });
  }

  function fmtDate(iso) {
    if (!iso) return null;
    var d = new Date(iso); if (isNaN(d)) return null;
    return d.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
  }
  function fmtDuration(a, b) {
    var s = Math.floor((new Date(b) - new Date(a)) / 1000), m = Math.floor(s / 60), h = Math.floor(m / 60), d = Math.floor(h / 24);
    if (d > 0) return h % 24 ? d + "d " + (h % 24) + "h" : d + "d";
    if (h > 0) return m % 60 ? h + "h " + (m % 60) + "m" : h + "h";
    if (m > 0) return s % 60 ? m + "m " + (s % 60) + "s" : m + "m";
    return s + "s";
  }
  // getRunStatusString
  function statusString(run) {
    var started = run.details.created_at, finished = run.details.finished_at;
    if (run.status === "SUCCEEDED") return finished ? "Finished " + fmtDate(finished) + (started ? " (" + fmtDuration(started, finished) + ")" : "") : "";
    if (run.status === "FAILED" && finished) return "Failed " + fmtDate(finished);
    return started ? "Started " + fmtDate(started) : "";
  }
  function prettyBytes(n) {
    n = num(n); if (n == null) return null;
    var u = ["B", "kB", "MB", "GB", "TB"], i = 0;
    while (n >= 1000 && i < u.length - 1) { n /= 1000; i++; }
    return (i ? Number(n.toPrecision(3)) : Math.round(n)) + " " + u[i];
  }
  function sentence(s) { s = String(s || "").toLowerCase(); return s.charAt(0).toUpperCase() + s.slice(1); }

  // ---- the run view ------------------------------------------------------------------------

  var COLS = [
    ["id", "ID", "ap-ad-c-id"], ["hypothesis", "Experiment hypothesis", "ap-ad-c-hyp"],
    ["surprisal", "Surprisal", "ap-ad-c-num"], ["prior", "Belief before", "ap-ad-c-belief"],
    ["posterior", "Belief after", "ap-ad-c-belief"], ["direction", "Direction", "ap-ad-c-dir"]
  ];
  function row(e) {
    var done = e.status === "SUCCEEDED";
    return {
      e: e, id: e.id, hypothesis: e.hypothesis || "N/A",
      surprisal: done && e.surprise != null ? Math.abs(e.surprise) : null,
      prior: done ? (e.labels ? e.labels.prior || "N/A" : beliefLabel(e.prior)) : "N/A", priorValue: done ? e.prior : null,
      posterior: done ? (e.labels ? e.labels.posterior || "N/A" : beliefLabel(e.posterior)) : "N/A", posteriorValue: done ? e.posterior : null,
      direction: done ? (e.labels ? e.labels.direction || "N/A" : direction(e.surprise)) : "N/A"
    };
  }

  function render(root, data) {
    var runs = (data.runs || []).map(loadRun);
    // A run with its results and its CSV download is drawn once, from the results.
    var named = {};
    runs.forEach(function (r) { if (r.kind !== "csv") named[slug(r.name)] = true; });
    runs = runs.filter(function (r) { return r.kind !== "csv" || !named[fileStem(r.source)]; });
    runs.forEach(function (r, i) { r.n = i + 1; r.anchor = "run-" + r.n; });
    if (!runs.length) { root.innerHTML = empty("No AutoDiscovery runs", "The page names no run files."); return; }
    var many = runs.length > 1;
    var state = { run: null, exp: null, sort: { field: "surprisal", dir: -1 }, text: "" };
    function expAnchor(run, e) { return (many ? run.anchor + "/" : "") + "experiment-" + e.id; }
    // Opening a run or an experiment is a step in the browser's history (pushState), so Back
    // returns to where the reader chose it: the earlier experiment, or the tree, at the scroll
    // position they left it, with the experiment they had open still marked. `shown` is the
    // fragment drawn last, so the panel's own steps, and a Back that fires both popstate and
    // hashchange, are drawn once. Scroll positions are kept per fragment in memory, which also
    // works when the app's site frame replays Back with location.replace (no history.state).
    var shown = hashOf(root), ypos = {};
    window.addEventListener("scroll", function () { if (shown != null) ypos[shown] = window.scrollY; }, { passive: true });
    function setHash(h) {
      var target = "#" + h;
      if (hashOf(root) === target) return;
      if (shown != null) ypos[shown] = window.scrollY;
      var url = urlOf(root, target);
      try { history.pushState(null, "", url); } catch (err) {
        try { history.replaceState(null, "", url); } catch (x) { /* a sandboxed frame may refuse */ }
      }
      shown = hashOf(root);
    }

    var listHtml = "";
    if (many) {
      listHtml = '<div class="ap-tt ap-ad-runs"><button type="button" class="ap-tt-head" aria-expanded="true">' + CHEVRON + "<h2>" +
        plural(runs.length, "AutoDiscovery run", "AutoDiscovery runs") + '</h2></button><div class="ap-tt-wrap"><table><thead><tr>' +
        '<th>Run</th><th class="ap-num">Experiments</th></tr></thead><tbody>' + runs.map(function (r, i) {
          return '<tr data-run="' + i + '"><td><div class="ap-tt-name-cell"><span class="ap-tt-name">' + esc((r.label ? r.label + " · " : "") + (r.title || r.name)) +
            "</span></div></td><td class=\"ap-num\">" + r.experiments.length + "</td></tr>";
        }).join("") + "</tbody></table></div></div>";
    }
    root.innerHTML = listHtml + '<div class="ap-ad-run"></div>';
    var runEl = root.querySelector(".ap-ad-run");
    if (many) {
      var tt = root.querySelector(".ap-ad-runs"), tog = tt.querySelector(".ap-tt-head");
      tog.addEventListener("click", function () { var c = tt.classList.toggle("ap-collapsed"); tog.setAttribute("aria-expanded", String(!c)); });
      tt.querySelectorAll("tbody tr").forEach(function (tr) {
        tr.addEventListener("click", function () { var r = runs[+tr.getAttribute("data-run")]; setHash(r.anchor); selectRun(r, null, true); });
      });
    }

    // The dialogs (Run Parameters, a figure at full size) sit over the page, in the panel's colours.
    var layer = document.createElement("div");
    layer.className = "asta-panel asta-autods ap-ad-layer";
    layer.hidden = true;
    layer.innerHTML = '<div class="ap-ad-dialog" role="dialog" aria-modal="true"><div class="ap-ad-dialog-head"><h3></h3>' +
      '<button type="button" class="ap-ad-x" aria-label="Close">' + icon(I.close) + '</button></div><div class="ap-ad-dialog-body"></div></div>';
    document.body.appendChild(layer);
    function openLayer(title, html) {
      layer.querySelector("h3").textContent = title;
      layer.querySelector(".ap-ad-dialog-body").innerHTML = html;
      layer.hidden = false;
      layer.querySelector(".ap-ad-x").focus();
    }
    layer.addEventListener("click", function (ev) { if (ev.target === layer || ev.target.closest(".ap-ad-x")) layer.hidden = true; });
    document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") layer.hidden = true; });

    function rowsOf(run) {
      var rows = run.experiments.map(row), q = state.text;
      if (q) rows = rows.filter(function (r) { return [r.id, r.hypothesis, r.prior, r.posterior, r.direction, r.surprisal != null ? r.surprisal.toFixed(3) : ""].join(" ").toLowerCase().indexOf(q) >= 0; });
      var f = state.sort.field, dir = state.sort.dir;
      if (f) {
        rows.sort(function (a, b) {
          var k = f === "prior" ? "priorValue" : f === "posterior" ? "posteriorValue" : f, x = a[k], y = b[k];
          if (x == null && y == null) return a.id - b.id;
          if (x == null) return 1;
          if (y == null) return -1;
          var c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
          return c * dir || a.id - b.id;
        });
      }
      return rows;
    }

    function selectRun(run, expKey, scroll) {
      state.run = run; state.exp = null; state.text = "";
      root.querySelectorAll(".ap-ad-runs tbody tr").forEach(function (tr) { tr.classList.toggle("ap-selected", +tr.getAttribute("data-run") === run.n - 1); });
      var n = run.experiments.length, surprising = run.experiments.filter(function (e) { return e.surprising; }).length;
      var chips = [sentence(run.status), statusString(run), run.requested && run.requested !== n ? n + " of " + run.requested + " experiments" : plural(n, "experiment", "experiments"),
        run.kind === "csv" ? "" : surprising + " surprising"].filter(Boolean);
      var links = [];
      if (run.link) links.push('<a href="' + esc(run.link) + '" target="_blank" rel="noopener noreferrer">Open in AutoDiscovery</a>');
      if (run.csvHref) links.push('<a href="' + esc(run.csvHref) + '" download>experiments.csv</a>');
      var h = run.hrefs;
      if (h.folder) links.push('<a href="' + esc(h.folder) + '" title="' + esc(run.source) + '">Run folder</a>');
      else if (h.file) links.push('<a href="' + esc(h.file) + '">' + esc(String(run.source).split("/").pop()) + "</a>");
      if (h.args) links.push('<a href="' + esc(h.args) + '">args.json</a>');
      if (h.runmd) links.push('<a href="' + esc(h.runmd) + '">run.md</a>');
      links.push('<button type="button" class="ap-ad-linkbtn" data-params>Session configuration</button>');
      runEl.id = run.anchor;
      runEl.innerHTML =
        '<div class="ap-theory-head"><h2>' + esc(run.name) + '<a class="ap-anchor" href="#' + esc(run.anchor) + '" title="Link to this run">#</a></h2>' +
        '<div class="ap-chips">' + chips.map(function (c) { return '<span class="ap-chip">' + esc(c) + "</span>"; }).join("") + "</div>" +
        '<div class="ap-ad-links">' + links.join("") + "</div></div>" +
        (run.tree ? '<div class="ap-ad-tree"><svg class="ap-ad-tree-svg" role="group" aria-label="The search tree"></svg>' +
          '<div class="ap-ad-zoom"><button type="button" data-zoom="in" aria-label="Zoom in">' + icon(I.plus) + '</button><button type="button" data-zoom="out" aria-label="Zoom out">' + icon(I.minus) + "</button>" +
          '<button type="button" data-zoom="reset" aria-label="Fit the tree" title="Fit the tree">' + icon(I.center) + "</button></div></div>" +
          '<p class="ap-legend">The search tree: each circle is an experiment, numbered as in the table and joined to the one it grew from. Orange marks a surprising result (an orange ring in the light theme), and the stronger the colour, the larger the surprisal. Click a circle to open its experiment; drag to move the tree.</p>'
          : "") +
        '<div class="ap-tt ap-ad-exps"><div class="ap-ad-exps-head"><button type="button" class="ap-tt-head" aria-expanded="true">' + CHEVRON + "<h2>" + plural(n, "experiment", "experiments") + "</h2></button>" +
        '<input type="search" class="ap-ad-search" placeholder="Filter experiments" aria-label="Filter experiments"></div>' +
        '<div class="ap-tt-wrap ap-ad-scroll"><table><thead><tr>' + COLS.map(function (c) {
          return '<th class="' + c[2] + '" aria-sort="none"><button type="button" data-sort="' + c[0] + '">' + esc(c[1]) + '<span class="ap-ad-sort" aria-hidden="true">' + icon(I.arrow) + "</span></button></th>";
        }).join("") + "</tr></thead><tbody></tbody></table></div>" +
        '<p class="ap-legend">Surprisal is how far the result moved AutoDiscovery\'s belief in the hypothesis, from 0 to 1; Direction says which way, toward true (positive) or false (negative).' +
        (run.kind === "csv" ? " This run is drawn from its CSV download, which keeps no search tree, code or figures." : "") + "</p></div>" +
        '<div class="ap-ad-exp"></div>';
      runEl.querySelector("[data-params]").addEventListener("click", function () { openParams(run); });
      var tt = runEl.querySelector(".ap-ad-exps"), tog = tt.querySelector(".ap-tt-head");
      tog.addEventListener("click", function () { var c = tt.classList.toggle("ap-collapsed"); tog.setAttribute("aria-expanded", String(!c)); });
      var input = runEl.querySelector(".ap-ad-search");
      input.addEventListener("input", function () { state.text = input.value.trim().toLowerCase(); drawRows(); });
      runEl.querySelectorAll("[data-sort]").forEach(function (b) {
        b.addEventListener("click", function () {
          var f = b.getAttribute("data-sort"), first = f === "surprisal" ? -1 : 1;
          if (state.sort.field !== f) state.sort = { field: f, dir: first };
          else if (state.sort.dir === first) state.sort = { field: f, dir: -first };
          else state.sort = { field: null, dir: 1 };
          drawRows();
        });
      });
      var tbody = runEl.querySelector("tbody");
      tbody.addEventListener("click", function (ev) { var tr = ev.target.closest && ev.target.closest("tr[data-key]"); if (tr) openExperiment(run.byKey[tr.getAttribute("data-key")]); });
      tbody.addEventListener("keydown", function (ev) {
        var tr = ev.target.closest && ev.target.closest("tr[data-key]");
        if (tr && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); openExperiment(run.byKey[tr.getAttribute("data-key")]); }
      });
      drawRows();
      if (run.tree) drawTree(run);
      var first = expKey ? run.byKey[expKey] : rowsOf(run)[0] && rowsOf(run)[0].e;
      if (first) showExperiment(first, false);
      if (scroll && runEl.scrollIntoView) runEl.scrollIntoView({ block: "start" });
    }

    function drawRows() {
      var run = state.run, rows = rowsOf(run);
      runEl.querySelectorAll("[data-sort]").forEach(function (b) {
        var on = b.getAttribute("data-sort") === state.sort.field;
        b.classList.toggle("ap-ad-sorted", on); b.classList.toggle("ap-ad-desc", on && state.sort.dir < 0);
        b.parentNode.setAttribute("aria-sort", on ? (state.sort.dir < 0 ? "descending" : "ascending") : "none");
      });
      runEl.querySelector(".ap-ad-exps tbody").innerHTML = rows.map(function (r) {
        var e = r.e;
        return '<tr tabindex="0" data-key="' + esc(e.key) + '"' + (state.exp === e ? ' class="ap-selected"' : "") + ">" +
          '<td class="ap-ad-c-id">' + esc(r.id) + '</td><td class="ap-ad-c-hyp"><div class="ap-ad-hyp">' + esc(r.hypothesis) + "</div></td>" +
          '<td class="ap-ad-c-num' + (e.surprising ? " ap-ad-surprising" : "") + '">' + (r.surprisal != null ? r.surprisal.toFixed(3) : "N/A") + "</td>" +
          '<td class="ap-ad-c-belief">' + esc(r.prior) + '</td><td class="ap-ad-c-belief">' + esc(r.posterior) + '</td><td class="ap-ad-c-dir">' + esc(r.direction) + "</td></tr>";
      }).join("") || '<tr><td colspan="6" class="ap-ad-none">No experiment matches the filter.</td></tr>';
    }

    function openExperiment(e) { setHash(expAnchor(state.run, e)); showExperiment(e, true); }

    function showExperiment(e, scroll) {
      var run = state.run;
      state.exp = e;
      runEl.querySelectorAll(".ap-ad-exps tbody tr").forEach(function (tr) { tr.classList.toggle("ap-selected", tr.getAttribute("data-key") === e.key); });
      if (run.paint) run.paint();
      var detail = runEl.querySelector(".ap-ad-exp"), anchor = expAnchor(run, e);
      var done = e.status === "SUCCEEDED";
      var chips = [];
      if (!done) chips.push('<span class="ap-chip ap-warn">' + esc(sentence(e.status)) + "</span>");
      if (e.surprising) chips.push('<span class="ap-chip ap-novel">Surprising</span>');
      if (done && e.surprise != null) chips.push('<span class="ap-chip">Surprisal ' + Math.abs(e.surprise).toFixed(3) + " · " + esc(direction(e.surprise)) + "</span>");
      var parent = e.parent && run.byKey[e.parent];
      if (parent) chips.push('<a class="ap-chip ap-ad-chiplink" href="#' + esc(expAnchor(run, parent)) + '">Grew from experiment ' + esc(parent.id) + "</a>");
      var figs = (e.figures || []).map(figure).filter(Boolean);
      var plan = e.plan || {};
      var result = [
        e.priorMean != null || e.posteriorMean != null ? section("Belief shift", beliefPlot(e)) : "",
        section(e.analysisLabel, md(e.analysis)),
        figs.length ? section(figs.length === 1 ? "Figure" : "Figures", '<div class="ap-ad-figs">' + figs.map(function (f, i) {
          return f.src ? '<button type="button" class="ap-ad-fig" data-fig="' + i + '"><img src="' + esc(f.src) + '" alt="Figure ' + (i + 1) + " of experiment " + esc(e.id) + '" loading="lazy"><span>Figure ' + (i + 1) + "</span></button>"
            : '<pre class="ap-ad-fig-text">' + esc(f.text) + "</pre>";
        }).join("") + "</div>") : "",
        section(e.reviewLabel, md(e.review))
      ].concat(e.extra.map(function (x) { return section(x[0], md(x[1])); })).join("");
      var planHtml = [section("Objective", md(plan.objective)), section("Steps", md(plan.steps)), section("Deliverables", md(plan.deliverables))].join("");
      var codeHtml = [section("Code", e.code ? codeBlock(e.code) : ""), section("Code output", e.codeOutput ? codeBlock(e.codeOutput) : "")].join("");
      var tabs = [["result", "Result", result || empty("No result", "This experiment recorded no analysis.")],
        ["plan", "Plan", planHtml || empty("No plan", "This run's files keep no plan for this experiment.")],
        ["code", "Code", codeHtml || empty("No code", run.kind === "csv" ? "The CSV download keeps no code." : "This experiment recorded no code.")]];
      var files = [];
      if (e.fileHref) files.push('<a href="' + esc(e.fileHref) + '">' + esc(e.file || "node file") + "</a>");
      if (e.fileHref && run.hrefs.richOutputs) files.push('<a href="' + esc(run.hrefs.richOutputs) + '">rich_outputs/</a>');
      detail.id = anchor;
      detail.innerHTML = '<div class="ap-theory-head"><h2>Experiment ' + esc(e.id) + '<a class="ap-anchor" href="#' + esc(anchor) + '" title="Link to this experiment">#</a></h2>' +
        (e.hypothesis ? "<p>" + inline(e.hypothesis) + "</p>" : "") +
        (chips.length ? '<div class="ap-chips">' + chips.join("") + "</div>" : "") +
        (files.length ? '<div class="ap-ad-links ap-ad-files"><span class="ap-files-label">Files</span>' + files.join("") + "</div>" : "") + "</div>" +
        '<div class="ap-tabs" role="tablist">' + tabs.map(function (t, k) {
          return '<button type="button" class="ap-tab" role="tab" data-tab="' + t[0] + '" aria-selected="' + (k === 0) + '">' + t[1] + "</button>";
        }).join("") + "</div>" + tabs.map(function (t, k) {
          return '<div class="ap-tabpanel ap-ad-panel" role="tabpanel" data-panel="' + t[0] + '"' + (k ? " hidden" : "") + ">" + t[2] + "</div>";
        }).join("");
      detail.querySelectorAll(".ap-tab").forEach(function (b) {
        b.addEventListener("click", function () {
          var name = b.getAttribute("data-tab");
          detail.querySelectorAll(".ap-tab").forEach(function (o) { o.setAttribute("aria-selected", String(o === b)); });
          detail.querySelectorAll(".ap-tabpanel").forEach(function (p) { p.hidden = p.getAttribute("data-panel") !== name; });
          placeBeliefLabels(detail);
        });
      });
      detail.querySelectorAll("[data-fig]").forEach(function (b) {
        b.addEventListener("click", function () {
          var i = +b.getAttribute("data-fig");
          openLayer("Experiment " + e.id + ", figure " + (i + 1), '<img class="ap-ad-fig-full" src="' + esc(figs[i].src) + '" alt="Figure ' + (i + 1) + '">');
        });
      });
      detail.querySelectorAll(".ap-ad-unfold").forEach(function (b) {
        b.addEventListener("click", function () {
          var block = b.closest(".ap-ad-code"), folded = block.classList.toggle("ap-ad-folded");
          b.querySelector("span").textContent = folded ? "Show all " + block.querySelectorAll(".ap-ad-line").length + " lines" : "Show fewer lines";
          b.classList.toggle("ap-ad-open", !folded);
        });
      });
      placeBeliefLabels(detail);
      if (scroll && detail.scrollIntoView) detail.scrollIntoView({ block: "start" });
    }

    // RunParametersModal
    function openParams(run) {
      var m = run.meta || {};
      var info = [["Discovery session name", run.name]];
      if (run.record.prompt) info.push(["Prompt", run.record.prompt]);
      else if (str(m.intent)) info.push(["Intent", str(m.intent)]);
      if (str(m.description)) info.push(["Dataset context", str(m.description)]);
      var ds = val(m.datasets);
      var STRATEGY = { ucb1_recursive: "UCB1 Recursive", pw: "Progressive Widening" };
      var settings = [
        ["Experiment budget", (num(m.n_experiments) || run.requested) + " experiments"],
        ["Exploration weight", num(m.exploration_weight) != null ? String(num(m.exploration_weight)) : "Default"],
        ["Search strategy", str(m.mcts_selection) ? STRATEGY[str(m.mcts_selection)] || str(m.mcts_selection) : "Not set"],
        ["Surprise threshold", num(m.surprisal_width) != null ? String(num(m.surprisal_width)) : "Default"],
        ["Evidence weight", num(m.evidence_weight) != null ? String(num(m.evidence_weight)) : "Default"]
      ];
      function field(f) { return section(f[0], '<p class="ap-ad-pre">' + esc(f[1]) + "</p>"); }
      openLayer("Session configuration",
        '<div class="ap-ad-params"><h4>Session info</h4>' + info.map(field).join("") +
        (Array.isArray(ds) && ds.length ? section("Datasets", ds.map(function (d) {
          var meta = [str(d.content_type || d.contentType), prettyBytes(d.file_size_bytes || d.fileSizeBytes)].filter(Boolean).join(" · ");
          return '<details class="ap-ad-dataset"><summary>' + CHEVRON + "<strong>" + esc(str(d.name)) + "</strong>" + (meta ? '<span class="ap-muted"> ' + esc(meta) + "</span>" : "") +
            '</summary><p class="ap-ad-pre">' + esc(str(d.description)) + "</p></details>";
        }).join("")) : "") +
        "<h4>Session settings</h4>" + (run.kind === "csv" ? '<p class="ap-legend">The CSV download does not record the settings.</p>' : settings.map(field).join("")) + "</div>");
    }

    // ExperimentGraph.tsx: the radial tree, each experiment's angle shared by its leaves. Its
    // colours are the page's: they are read from the theme and redrawn when it changes.
    function drawTree(run) {
      var box = runEl.querySelector(".ap-ad-tree"), svg = box.querySelector("svg"), NS = "http://www.w3.org/2000/svg";
      function el(name, attrs) { var x = document.createElementNS(NS, name); for (var k in attrs) x.setAttribute(k, attrs[k]); return x; }
      var all = run.experiments, orphan = null;
      all.forEach(function (e) { if (e.parent && !run.byKey[e.parent]) orphan = orphan || e.parent; });
      // The dataset-load node is never an experiment; its children name it, so it is drawn faded.
      var rootExp = orphan ? { key: orphan, id: "", fake: true } : all.filter(function (e) { return !e.parent; })[0];
      if (!rootExp) return;
      function toTree(e, depth) {
        var t = { e: e, depth: depth, children: [] };
        all.forEach(function (c) { if (c.parent === e.key && c !== e) { var k = toTree(c, depth + 1); k.parent = t; t.children.push(k); } });
        return t;
      }
      var tree = toTree(rootExp, 0), nodes = [];
      (function walk(t) { nodes.push(t); t.children.forEach(walk); })(tree);
      function leaves(t) { return t.children.length ? t.children.reduce(function (s, c) { return s + leaves(c); }, 0) : 1; }
      var tf = { x: 0, y: 0, k: 1 }, moved = false, g = null, circles = {}, lines = [], colours = {};
      function cssVar(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
      function rgb(c) {
        var m = /^#([0-9a-f]{6})$/i.exec(c);
        if (m) return [0, 2, 4].map(function (i) { return parseInt(m[1].slice(i, i + 2), 16); });
        m = /rgba?\(([^)]+)\)/.exec(c);
        return m ? m[1].split(",").slice(0, 3).map(function (x) { return +x; }) : [128, 128, 128];
      }
      function mix(a, b, k) { return "rgb(" + a.map(function (v, i) { return Math.round(v + (b[i] - v) * k); }).join(",") + ")"; }
      function tint(e) {
        var k = Math.max(0, Math.min(1, Math.abs(e.surprise) / 0.7));
        return mix(rgb(colours.base), rgb(e.surprising ? colours.hot : colours.cool), 0.25 + 0.75 * k);
      }
      // In the light theme a surprising experiment is drawn as an outline, not a filled disc.
      function outlined(e) { return colours.light && !e.fake && e.surprising && typeof e.surprise === "number"; }
      function fill(e) {
        if (e.fake || typeof e.surprise !== "number") return colours.base;
        return outlined(e) ? colours.bg : tint(e);
      }
      function apply() { if (g) g.setAttribute("transform", "translate(" + tf.x + "," + tf.y + ") scale(" + tf.k + ")"); }
      function pathOf(t) { var s = {}; for (var c = t; c; c = c.parent) s[c.e.key] = true; return s; }
      function paint(hover) {
        var sel = nodes.filter(function (t) { return t.e === state.exp; })[0], sp = sel ? pathOf(sel) : {}, hp = hover ? pathOf(hover) : {};
        nodes.forEach(function (t) {
          var c = circles[t.e.key]; if (!c) return;
          var isSel = t.e === state.exp;
          var o = outlined(t.e);
          c.setAttribute("stroke", isSel ? colours.select : hp[t.e.key] && !t.e.fake ? colours.text : o ? tint(t.e) : colours.bg);
          c.setAttribute("stroke-width", isSel ? 3.5 : o ? 3 : 1.5);
        });
        lines.forEach(function (l) {
          var on = sp[l.s.e.key] && sp[l.d.e.key], hov = hp[l.s.e.key] && hp[l.d.e.key];
          l.el.setAttribute("stroke", on ? colours.select : hov ? colours.text : colours.line);
          l.el.setAttribute("stroke-width", on || hov ? 2.5 : 1.2);
        });
      }
      function draw() {
        colours = { base: cssVar("--ap-sunk") || "#f0eae1", cool: cssVar("--ap-faint") || "#6e9291", hot: cssVar("--ap-surprise") || "#e08a00",
          line: cssVar("--ap-line") || "#cbd2cc", text: cssVar("--ap-text") || "#0a3235", bg: cssVar("--ap-raised") || "#fff", select: cssVar("--ap-accent") || "#f0529c" };
        (function () { var b = rgb(colours.bg); colours.light = (0.2126 * b[0] + 0.7152 * b[1] + 0.0722 * b[2]) / 255 > 0.5; })();
        while (svg.firstChild) svg.removeChild(svg.firstChild);
        var w = box.clientWidth || 800, h = box.clientHeight || 440;
        var radius = Math.min(w, h) / 2 - 28, maxDepth = Math.max.apply(null, nodes.map(function (t) { return t.depth; })) || 1;
        nodes.forEach(function (t) { t.r = (t.depth / maxDepth) * radius; });
        (function assign(t, a0, a1) {
          t.angle = (a0 + a1) / 2; t.x = t.r * Math.cos(t.angle); t.y = t.r * Math.sin(t.angle);
          if (!t.children.length) return;
          var total = t.children.reduce(function (s, c) { return s + leaves(c); }, 0), cur = a0;
          t.children.forEach(function (c) { var span = leaves(c) / total * (a1 - a0); assign(c, cur, cur + span); cur += span; });
        })(tree, 0, 2 * Math.PI);
        g = el("g", {}); var lg = el("g", {}), ng = el("g", {});
        g.appendChild(lg); g.appendChild(ng); svg.appendChild(g);
        lines = []; circles = {};
        nodes.forEach(function (t) { t.children.forEach(function (c) {
          var line = el("line", { x1: t.x, y1: t.y, x2: c.x, y2: c.y });
          lines.push({ s: t, d: c, el: line }); lg.appendChild(line);
        }); });
        var r = nodes.length > 80 ? 11 : 15;
        nodes.forEach(function (t) {
          var c = el("circle", { cx: t.x, cy: t.y, r: t.e.fake ? r * 0.6 : r, fill: fill(t.e), opacity: t.e.fake ? 0.5 : 1 });
          circles[t.e.key] = c; ng.appendChild(c);
          if (t.e.fake) return;
          var tip = el("title", {}); tip.textContent = "Experiment " + t.e.id + ": " + t.e.hypothesis; c.appendChild(tip);
          c.setAttribute("tabindex", "0"); c.setAttribute("role", "button"); c.setAttribute("aria-label", "Experiment " + t.e.id);
          c.style.cursor = "pointer";
          c.addEventListener("mouseover", function () { paint(t); });
          c.addEventListener("mouseout", function () { paint(null); });
          c.addEventListener("click", function () { openExperiment(t.e); });
          c.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openExperiment(t.e); } });
          var label = el("text", { x: t.x, y: t.y, "text-anchor": "middle", "dominant-baseline": "central", "pointer-events": "none", "font-size": r > 12 ? "11px" : "9px", "font-weight": "700" });
          label.setAttribute("fill", !outlined(t.e) && t.e.surprising && Math.abs(t.e.surprise || 0) > 0.35 ? "#0a3235" : colours.text);
          label.textContent = t.e.id; ng.appendChild(label);
        });
        paint(null);
        if (!moved) tf = { x: w / 2, y: h / 2, k: 1 };
        apply();
      }
      run.paint = function () { paint(null); };
      var drag = null;
      svg.addEventListener("mousedown", function (ev) { if (ev.button === 0) drag = { x: ev.clientX, y: ev.clientY, tx: tf.x, ty: tf.y }; });
      window.addEventListener("mousemove", function (ev) { if (!drag) return; tf.x = drag.tx + ev.clientX - drag.x; tf.y = drag.ty + ev.clientY - drag.y; moved = true; apply(); });
      window.addEventListener("mouseup", function () { drag = null; });
      box.querySelectorAll("[data-zoom]").forEach(function (b) {
        b.addEventListener("click", function () {
          var kind = b.getAttribute("data-zoom"), cx = box.clientWidth / 2, cy = box.clientHeight / 2;
          if (kind === "reset") { moved = false; tf = { x: cx, y: cy, k: 1 }; apply(); return; }
          var k = Math.max(0.4, Math.min(3, tf.k * (kind === "in" ? 1.3 : 0.77)));
          tf = { k: k, x: cx - (cx - tf.x) * (k / tf.k), y: cy - (cy - tf.y) * (k / tf.k) }; moved = true; apply();
        });
      });
      draw();
      if (window.ResizeObserver) new ResizeObserver(function () { if (state.run === run) draw(); }).observe(box);
      // Quarto's light/dark switch changes the body's class; the tree takes the new colours.
      new MutationObserver(function () { if (state.run === run) draw(); }).observe(document.body, { attributes: true, attributeFilter: ["class"] });
    }

    function fromHash(back) {
      var h = hashOf(root) || "";
      try { h = decodeURIComponent(h.slice(1)); } catch (err) { h = ""; }
      var run = runs[0], rest = h;
      // A local run's node id names an experiment too: #node-3-1 or #node_3_1 (any run's,
      // or #run-2/node-3-1).
      function byNode(r, s) {
        var nm = /^node[-_](\d+)[-_](\d+)$/.exec(s || "");
        return nm ? r.experiments.filter(function (x) { return x.key === "node_" + nm[1] + "_" + nm[2]; })[0] || null : null;
      }
      if (many) {
        var m = /^run-(\d+)(?:\/(.*))?$/.exec(h);
        if (m && runs[+m[1] - 1]) { run = runs[+m[1] - 1]; rest = m[2] || ""; }
        else {
          rest = "";
          runs.some(function (r) { if (byNode(r, h)) { run = r; rest = h; return true; } return false; });
        }
      }
      var em = /^experiment-(.+)$/.exec(rest || ""), e = null;
      if (em) e = run.experiments.filter(function (x) { return String(x.id) === em[1]; })[0] || null;
      else e = byNode(run, rest);
      var saved = back ? ypos[hashOf(root)] : null;
      if (state.run !== run) selectRun(run, e ? e.key : null, !back && !!h && !e);
      if (e) showExperiment(e, saved == null);
      // Back to a fragment with no experiment (the run, or the page itself): the tree again,
      // with the experiment last opened still marked.
      if (back && saved == null && !e && runEl.scrollIntoView) runEl.scrollIntoView({ block: "start" });
      if (saved != null) window.scrollTo(0, saved);
    }
    // Back and Forward fire popstate, and hashchange too when the fragment differs; a link or
    // the app's site frame fires hashchange alone.
    function onAddress() {
      var h = hashOf(root);
      if (h == null || h === shown) return; // another page's address, or this panel's own step
      shown = h;
      fromHash(true);
    }
    window.addEventListener("hashchange", onAddress);
    window.addEventListener("popstate", onAddress);
    // "Grew from experiment N" chips are in-page links: route them through the same history step.
    root.addEventListener("click", function (ev) {
      var a = ev.target.closest && ev.target.closest("a.ap-ad-chiplink");
      if (!a) return;
      var m = /experiment-(.+)$/.exec(decodeURIComponent(a.getAttribute("href") || ""));
      var e = m && state.run && state.run.experiments.filter(function (x) { return String(x.id) === m[1]; })[0];
      if (e) { ev.preventDefault(); openExperiment(e); }
    });
    window.addEventListener("resize", function () { placeBeliefLabels(root); });
    fromHash();
  }

  function safeRender(root, readData) {
    try {
      render(root, readData());
    } catch (e) {
      root.innerHTML = '<div class="ap-error">The AutoDiscovery run could not be read (' + esc(e.message) +
        "). The page's data should name the run's results JSON (asta autodiscovery results), its CSV or JSON download, its output folder or its run folder.</div>";
    }
  }
  window.AstaTemplates = window.AstaTemplates || {};
  window.AstaTemplates.autods = safeRender;

  // Each AutoDiscovery panel in scope draws itself, once, from the data script that follows it.
  // asta-templates.js calls start on a page appended to a flow's feed, so a document can hold
  // several pages' panels.
  function start(scope) {
    scope = scope || document;
    scope.querySelectorAll(".asta-panel.asta-autods").forEach(function (root) {
      if (root.hasAttribute("data-asta-drawn")) return;
      var src = root.nextElementSibling;
      if (!src || !/^script$/i.test(src.tagName) || !/asta-autods-data$/.test(src.id || "")) src = document.getElementById("asta-autods-data");
      if (!src) return;
      root.setAttribute("data-asta-drawn", "");
      safeRender(root, function () { return JSON.parse(src.textContent); });
    });
  }
  window.AstaTemplates.widgets = window.AstaTemplates.widgets || [];
  window.AstaTemplates.widgets.push({ name: "autods", order: 1, start: start });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { start(document); });
  else start(document);
})();
