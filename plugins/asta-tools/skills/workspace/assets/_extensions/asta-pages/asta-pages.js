/* asta-pages core: what the widget scripts share, and a flow's feed.

   Widgets. Each widget script (theories.js, tests.js, autods.js, literature.js) adds its start
   function to AstaPages.widgets; start(scope) draws the panels in scope that are not drawn yet.
   AstaPages.init(scope) runs them all (tests first, which the theories' Tests tab links to), so
   a page appended below this one draws its panels the same way the page itself did.

   Addresses. A panel's anchors (#theory-2, #test-G2-T1, #experiment-7, #paper-…) belong to the
   page it came from. AstaPages.hashOf(el) is the address's fragment when the address is that
   page's (null otherwise), and AstaPages.urlOf(el, "#x") the URL a panel pushes for a step of
   its own: the fragment alone on its own page, the page's URL with it on another. So a panel
   of an appended page answers only to its own page's address, and Back steps through each
   page's panels as before.

   Sections. Under each sidebar link to a page, that page's sections (script#asta-sections,
   written by asta-pages.lua: its level-2 headings and their ids), folded with Quarto's chevron:
   the page the reader is on open, the others shut. The section in view is marked as the reader
   scrolls, on the page in view. "On this page" is hidden while it lists exactly those sections,
   and shows when it has more (a page's subsections).

   Feed. A page says where the site's root is (script#asta-flow, written by asta-pages.lua); the
   feed's pages are the sidebar's links into the site, once each, in the sidebar's order: in a
   workspace the front page, then the workflow pages in run order.
   When the reader is about a screen from the end of the page, the next page is fetched (same
   origin, relative URL), its main content appended under a divider (its title linking the page
   itself, and where it stands in the sidebar), the stylesheets and scripts it
   needs and this page lacks loaded, and its panels drawn; and so on to the last page,
   which ends with a quiet "End". As a later page scrolls into view the address
   becomes that page's (history.replaceState, so Back is unchanged and a reload or a shared link
   lands on that page), the window title its title, and the sidebar marks it. Each page is
   fetched once; a failed fetch shows a retry. Uses no browser storage. */
(function () {
  "use strict";

  var A = window.AstaPages = window.AstaPages || {};
  A.widgets = A.widgets || [];
  if (A.flow) return; // loaded once

  function noHash(u) { return String(u || "").split("#")[0]; }
  // A page's address: a folder's is its index.html (Quarto links the front page as the site's
  // root, "./").
  function canon(u) { u = noHash(u); return /\/$/.test(u) ? u + "index.html" : u; }
  function samePage(a, b) { return canon(a) === canon(b); }
  var FIRST = noHash(location.href);
  A.firstUrl = FIRST;

  function sectionOf(el) { return (el && el.closest && el.closest(".asta-flow-page")) || null; }
  // The URL of the page an element came from: an appended page's, else this page's.
  A.pageUrl = function (el) { var s = sectionOf(el); return s ? s.getAttribute("data-asta-url") : FIRST; };
  // Where an element's page lookups go: its appended page, or the document.
  A.scope = function (el) { return sectionOf(el) || document; };
  // A reading position (#flow-at=..., below) is no panel's anchor: to the panels it is no fragment.
  var POS = /^#flow-at=/;
  A.hashOf = function (el) {
    if (noHash(location.href) !== A.pageUrl(el)) return null;
    return POS.test(location.hash) ? "" : location.hash;
  };
  A.urlOf = function (el, hash) {
    var u = A.pageUrl(el);
    return u === noHash(location.href) ? hash : u + hash;
  };
  A.init = function (scope) {
    A.widgets.slice().sort(function (a, b) { return (a.order || 0) - (b.order || 0); }).forEach(function (w) {
      try { w.start(scope || document); } catch (e) { if (window.console) console.error(e); }
    });
  };

  // ---- the feed ------------------------------------------------------------------------------

  var SKIP_URL = /^(?:#|\/|[a-z][a-z0-9+.-]*:)/i;
  // Relative links and sources in el, made absolute paths from base (the page they came from),
  // so they keep pointing at the right files whatever the address is.
  function fixLinks(el, base) {
    if (!el || el.nodeType !== 1) return;
    var list = [el].concat([].slice.call(el.querySelectorAll("[href],[src]")));
    list.forEach(function (n) {
      ["href", "src"].forEach(function (attr) {
        var v = n.getAttribute(attr);
        if (v == null || v === "" || SKIP_URL.test(v)) return;
        if (n.tagName === "LINK" || n.tagName === "SCRIPT") return;
        try {
          var u = new URL(v, base);
          n.setAttribute(attr, u.origin === location.origin ? u.pathname + u.search + u.hash : u.href);
        } catch (e) { /* leave it */ }
      });
    });
  }

  function dirOf(u) { return noHash(u).replace(/[?].*$/, "").replace(/[^/]*$/, ""); }


  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ---- cards -------------------------------------------------------------------------------
  // A link that autolink.lua gave a card (a test, a theory, a gap, an experiment, a figure, a
  // paper or dataset or site, a citation, an evidence claim, a workspace file) names it in
  // data-asta-card: a key into the page's cards (script.asta-cards-data; a page appended to a
  // flow's feed brings its own). Every card is the same kind of thing, drawn here the same way:
  // sections, each with any of a role, a title (linked), a sub line, a thumbnail, a quote, text
  // clamped to some lines, a test's verdict, tests' verdicts, a tally of verdicts, facts and
  // links; then a footer. Hovering the link, focusing it or tapping it opens its card beside
  // it (never over it); the card stays while the pointer is on it; Esc, a click elsewhere, or
  // the pointer leaving both for a moment closes it. The link's own hover (Quarto's reference
  // and cross-reference previews, a native title, the evidence popover) gives way to it.
  A.cards = (function () {
    var card = null, owner = null, openTimer = 0, closeTimer = 0, touch = false, seq = 0, quiet = null;
    var stores = [];
    function mention(el) { return el && el.closest ? el.closest("[data-asta-card]") : null; }
    function inCard(el) { return !!(card && el && card.contains(el)); }
    function urlFor(a, href) {
      try { return new URL(href, A.pageUrl(a)).href; } catch (e) { return href; }
    }
    // The card a link names: from its page's store (or, written whole, the attribute itself).
    function spec(a) {
      var key = a.getAttribute("data-asta-card") || "";
      if (key.charAt(0) === "{") { try { return JSON.parse(key); } catch (e) { return null; } }
      var scope = A.scope(a), el = scope.querySelector ? scope.querySelector("script.asta-cards-data") : null;
      if (!el) return null;
      var hit = stores.filter(function (x) { return x.el === el; })[0];
      if (!hit) {
        var data = {};
        try { data = JSON.parse(el.textContent) || {}; } catch (e) { data = {}; }
        hit = { el: el, data: data };
        stores.push(hit);
      }
      return hit.data[key] || null;
    }
    var SHORT = { met: "met", partial: "partly met", notmet: "not met", undecided: "undecided", running: "running",
      notrun: "not run", notstarted: "not started" };
    function testLine(t) {
      var lib = A.testsLib;
      if (!lib || !t) return "";
      var v = lib.verdict(t), n = lib.numbers(t), bits = [];
      if (n.effect && n.effect.text && n.effect.text !== "—") bits.push("effect " + esc(n.effect.text));
      if (n.p && n.p.text && n.p.text !== "—") bits.push("p " + esc(n.p.text));
      if (n.n && n.n.text && n.n.text !== "—") bits.push(esc(n.n.text) + " mice");
      return '<div class="ap-al-meta">' + lib.verdictChip(v) + (bits.length ? " <span>" + bits.join(" · ") + "</span>" : "") + "</div>";
    }
    function chips(tests) {
      var lib = A.testsLib;
      if (!lib) return "";
      return '<div class="ap-al-chips">' + tests.map(function (t) {
        var v = lib.verdict(t);
        return '<span class="ap-chip ap-v ap-v-' + esc(v.key) + '">' + esc(t.id) + " · " + esc(SHORT[v.key] || v.label) + "</span>";
      }).join("") + "</div>";
    }
    function tally(tests) {
      var lib = A.testsLib;
      if (!lib) return "";
      var c = {}, order = [];
      tests.forEach(function (t) { var k = lib.verdict(t).key; if (!c[k]) { c[k] = 0; order.push(k); } c[k]++; });
      order.sort(function (a, b) { return Object.keys(SHORT).indexOf(a) - Object.keys(SHORT).indexOf(b); });
      return '<div class="ap-al-meta">' + tests.length + (tests.length === 1 ? " test: " : " tests: ") +
        order.map(function (k) { return c[k] + " " + esc(SHORT[k] || k); }).join(" · ") + "</div>";
    }
    function clamp(n) { return n ? ' style="-webkit-line-clamp:' + (+n) + '"' : ""; }
    function section(a, s) {
      var h = "";
      if (s.role) h += '<div class="ap-al-role">' + esc(s.role) + "</div>";
      if (s.image) h += '<img class="ap-al-thumb" src="' + esc(urlFor(a, s.image)) + '" alt="" loading="lazy">';
      if (s.title) {
        h += s.href ? '<a class="ap-al-go ap-al-clamp" href="' + esc(urlFor(a, s.href)) + '"' +
          (s.external ? ' target="_blank" rel="noopener"' : "") + clamp(s.title_clamp) + ">" +
          esc(s.title) + ' <span aria-hidden="true">' + (s.external ? "↗" : "→") + "</span></a>"
          : '<div class="ap-al-title ap-al-clamp"' + clamp(s.title_clamp) + ">" + esc(s.title) + "</div>";
      }
      if (s.sub) h += '<div class="ap-al-page">' + esc(s.sub) + "</div>";
      if (s.quote) h += '<blockquote class="ap-al-quote ap-al-clamp"' + clamp(s.clamp) + ">“" + esc(s.quote) + "”</blockquote>";
      if (s.text) h += '<p class="ap-al-text ap-al-clamp"' + clamp(s.clamp) + ">" + esc(s.text) + "</p>";
      if (s.test) h += testLine(s.test);
      if (s.tests && s.tests.length) h += chips(s.tests);
      if (s.facts && s.facts.length) h += '<div class="ap-al-meta"><span>' + s.facts.map(esc).join(" · ") + "</span></div>";
      if (s.tally && s.tally.length) h += tally(s.tally);
      if (s.links && s.links.length) {
        h += '<div class="ap-al-links">' + s.links.map(function (l) {
          return '<a href="' + esc(urlFor(a, l.href)) + '"' + (l.external ? ' target="_blank" rel="noopener"' : "") + ">" +
            esc(l.label) + ' <span aria-hidden="true">' + (l.external ? "↗" : "→") + "</span></a>";
        }).join("") + "</div>";
      }
      return '<div class="ap-al-item">' + h + "</div>";
    }
    // Where a workspace file opens: on GitHub once a deployed site's links point there, in the
    // app's Files tab inside the app's frame, else the file itself.
    function fileFoot(a) {
      var href = a.getAttribute("href") || "";
      if (/^https?:\/\/github\.com\//.test(href)) return "Opens on GitHub.";
      return window.top !== window ? "Opens in Files." : "Opens the file.";
    }
    function build(a, d) {
      var el = document.createElement("div");
      el.className = "asta-panel asta-al-card";
      el.id = "asta-al-card-" + (++seq);
      el.setAttribute("role", "dialog");
      el.setAttribute("aria-label", d.text || a.textContent || "Details");
      var foot = d.file ? fileFoot(a) : d.foot;
      el.innerHTML = (d.sections || []).map(function (s) { return section(a, s); }).join("") +
        (foot ? '<div class="ap-al-foot">' + esc(foot) + "</div>" : "");
      return el;
    }
    // Below the mention, or above it when there is no room below; inside the window sideways.
    function place(a) {
      if (!card || !a.getBoundingClientRect) return;
      var r = a.getBoundingClientRect(), w = card.offsetWidth || 0, h = card.offsetHeight || 0, gap = 6;
      var vw = document.documentElement.clientWidth || window.innerWidth, vh = window.innerHeight;
      var top = r.bottom + gap;
      if (top + h > vh && r.top - gap - h > 0) top = r.top - gap - h;
      var left = Math.max(8, Math.min(r.left, vw - w - 8));
      card.style.top = (top + (window.scrollY || 0)) + "px";
      card.style.left = (left + (window.scrollX || 0)) + "px";
    }
    function close(refocus) {
      clearTimeout(openTimer); clearTimeout(closeTimer);
      if (!card) return;
      var a = owner;
      if (card.parentNode) card.parentNode.removeChild(card);
      card = null; owner = null;
      if (a) {
        a.setAttribute("aria-expanded", "false");
        a.removeAttribute("aria-controls");
        if (refocus && a.focus) { quiet = a; a.focus(); quiet = null; } // back on it, the card stays shut
      }
    }
    function open(a) {
      clearTimeout(openTimer); clearTimeout(closeTimer);
      if (owner === a && card) return;
      close(false);
      var d = spec(a);
      if (!d || !Array.isArray(d.sections) || !d.sections.length) return;
      card = build(a, d);
      owner = a;
      document.body.appendChild(card);
      a.setAttribute("aria-expanded", "true");
      a.setAttribute("aria-controls", card.id);
      place(a);
    }
    function closeSoon() { clearTimeout(closeTimer); closeTimer = setTimeout(function () { close(false); }, 300); }
    document.addEventListener("mouseover", function (ev) {
      var a = mention(ev.target);
      if (a) {
        clearTimeout(closeTimer);
        if (owner !== a) { clearTimeout(openTimer); openTimer = setTimeout(function () { open(a); }, 120); }
      } else if (inCard(ev.target)) clearTimeout(closeTimer);
    });
    document.addEventListener("mouseout", function (ev) {
      var from = mention(ev.target) || (inCard(ev.target) ? card : null);
      if (!from) return;
      var to = ev.relatedTarget;
      if (to && (inCard(to) || (owner && owner.contains(to)) || mention(to) === from)) return;
      clearTimeout(openTimer);
      if (card) closeSoon();
    });
    document.addEventListener("focusin", function (ev) {
      var a = mention(ev.target);
      if (a) { if (a !== quiet) open(a); return; }
      if (card && !inCard(ev.target)) close(false);
    });
    document.addEventListener("pointerdown", function (ev) {
      touch = ev.pointerType === "touch" || ev.pointerType === "pen";
      if (card && !inCard(ev.target) && !(owner && owner.contains(ev.target))) close(false);
    }, true);
    // On a touch screen a first tap opens the card; a tap on the opened mention follows it.
    document.addEventListener("click", function (ev) {
      var a = mention(ev.target);
      if (a && touch && owner !== a) { ev.preventDefault(); open(a); }
    });
    document.addEventListener("keydown", function (ev) {
      if (!card) return;
      if (ev.key === "Escape") { close(true); return; }
      if (ev.key !== "Tab") return;
      var links = card.querySelectorAll("a[href]");
      if (!links.length) return;
      // Tab from the mention goes into its card, Shift+Tab from its first link back out.
      if (!ev.shiftKey && document.activeElement === owner) { ev.preventDefault(); links[0].focus(); }
      else if (ev.shiftKey && document.activeElement === links[0]) { ev.preventDefault(); owner.focus(); }
    });
    window.addEventListener("resize", function () { if (owner) place(owner); });
    // The link's own hover gives way: a native title, Quarto's reference and cross-reference
    // previews (tippy, set up when the page loads), and the evidence popover, which evidence
    // draws with CSS and which html.asta-cards hides (asta-pages.css) where a card stands in.
    function quiet_links() {
      document.querySelectorAll("[data-asta-card]").forEach(function (el) {
        [el].concat([].slice.call(el.querySelectorAll ? el.querySelectorAll("a, [title]") : [])).forEach(function (n) {
          if (n._tippy && n._tippy.destroy) { try { n._tippy.destroy(); } catch (e) { /* gone */ } }
          if (n.removeAttribute && !(n.closest && n.closest(".ev-pop"))) n.removeAttribute("title");
        });
      });
    }
    document.documentElement.classList.add("asta-cards");
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { setTimeout(quiet_links, 0); });
    } else setTimeout(quiet_links, 0);
    window.addEventListener("load", quiet_links);
    return { open: open, close: close, current: function () { return card; }, quiet: quiet_links };
  })();

  // The stylesheets and scripts a fetched page names that this document lacks, in its order.
  // Every link this document has counts, whatever its rel: Quarto turns the colour scheme it is
  // not showing into a disabled link, which must not come back as a live stylesheet.
  function missingAssets(doc, base) {
    var have = {};
    document.querySelectorAll("script[src], link[href]").forEach(function (n) {
      try { have[new URL(n.getAttribute(n.tagName === "SCRIPT" ? "src" : "href"), FIRST).href] = true; } catch (e) { /* skip */ }
    });
    var out = [];
    doc.querySelectorAll('script[src], link[rel="stylesheet"][href]:not(.quarto-color-scheme)').forEach(function (n) {
      var raw = n.getAttribute(n.tagName === "SCRIPT" ? "src" : "href"), url;
      try { url = new URL(raw, base).href; } catch (e) { return; }
      if (have[url]) return;
      have[url] = true;
      out.push({ tag: n.tagName, url: url, module: n.getAttribute("type") === "module" });
    });
    return out;
  }

  function loadAsset(a) {
    return new Promise(function (resolve) {
      var n;
      if (a.tag === "SCRIPT") {
        n = document.createElement("script");
        if (a.module) n.type = "module";
        n.src = a.url;
      } else {
        n = document.createElement("link");
        n.rel = "stylesheet";
        n.href = a.url;
      }
      n.onload = n.onerror = function () { resolve(); };
      document.head.appendChild(n);
    });
  }

  function loadAssets(list) {
    // Stylesheets at once; scripts one after another, in the page's order.
    var css = list.filter(function (a) { return a.tag !== "SCRIPT"; }).map(loadAsset);
    return list.filter(function (a) { return a.tag === "SCRIPT"; }).reduce(function (p, a) {
      return p.then(function () { return loadAsset(a); });
    }, Promise.all(css));
  }

  // The fetched page's main content, ready to append: its own title block left out (the divider
  // carries the title), its ids prefixed so they stay unique in this document, its relative
  // links made absolute from its own URL.
  function extract(doc, url, prefix) {
    var main = doc.getElementById("quarto-document-content") || doc.querySelector("main") || doc.body;
    if (!main) return null;
    ["#title-block-header", "script#asta-flow", ".asta-flow"].forEach(function (sel) {
      main.querySelectorAll(sel).forEach(function (n) { n.parentNode.removeChild(n); });
    });
    var box = document.createElement("div");
    box.className = "asta-flow-content";
    while (main.firstChild) box.appendChild(main.firstChild); // moved, and adopted, from the fetched page
    box.querySelectorAll("[id]").forEach(function (n) { n.id = prefix + n.id; });
    box.querySelectorAll("[data-asta-data]").forEach(function (n) {
      n.setAttribute("data-asta-data", prefix + n.getAttribute("data-asta-data"));
    });
    ["aria-labelledby", "aria-controls", "aria-describedby", "for"].forEach(function (attr) {
      box.querySelectorAll("[" + attr + "]").forEach(function (n) {
        n.setAttribute(attr, n.getAttribute(attr).split(/\s+/).map(function (x) { return x && prefix + x; }).join(" "));
      });
    });
    fixLinks(box, url);
    return box;
  }

  // The fetched page's own "On this page" list, its links aimed at the page's appended headings.
  function tocOf(doc, prefix) {
    var ul = doc.querySelector('nav[role="doc-toc"] > ul');
    if (!ul) return null;
    ul = document.importNode(ul, true);
    ul.querySelectorAll("[id]").forEach(function (n) { n.id = prefix + n.id; });
    ul.querySelectorAll("a").forEach(function (a) {
      a.classList.remove("active");
      var h = a.getAttribute("href") || "";
      if (h.charAt(0) !== "#") return;
      var id = h.slice(1);
      try { id = decodeURIComponent(id); } catch (e) { /* as written */ }
      a.setAttribute("data-asta-target", prefix + id);
      a.setAttribute("data-scroll-target", "#" + prefix + id);
    });
    return ul;
  }

  // ---- reading position ----------------------------------------------------------------------
  // Where the reader is, kept in the address while they read a flow's page: #flow-at=<id>~<px>,
  // the last of the page's sections (Quarto's section ids) above the top of the window and how
  // far below its top the window is. It is written with history.replaceState, only over no
  // fragment, a heading's or an earlier position (never over a panel's anchor). The app's site
  // frame keeps the address but not history.state (it moves the frame with location.replace),
  // so Back to a page the reader left, from the Files tab or elsewhere, opens the page at that
  // address, and the page scrolls back to the same place within the same section. A page
  // appended in a feed has the same section ids as the page on its own, so the place carries
  // over from one to the other.
  //
  // A panel's own scrolling list (the tests table, an AutoDiscovery run's experiments, a
  // theory's evidence) scrolls inside the page, not the window: its offset is kept too, as
  // "~<n>:<px>" for the n-th such list of the page (#flow-at=tests~803~0:850).
  var SCROLLERS = ".ap-ts-scroll, .ap-ad-scroll, .ap-ev-table-wrap";
  function parsePos(h) {
    var m = /^#flow-at=([^~]*)~(-?\d+)(?:~([\d:.]+))?$/.exec(h || "");
    if (!m) return null;
    var id = m[1];
    try { id = decodeURIComponent(id); } catch (e) { /* as written */ }
    var inner = (m[3] || "").split(".").filter(Boolean).map(function (x) { return x.split(":").map(Number); });
    return { id: id, y: +m[2], inner: inner };
  }
  var restoring = parsePos(location.hash);
  if (restoring && "scrollRestoration" in history) {
    try { history.scrollRestoration = "manual"; } catch (e) { /* not settable */ }
  }
  function restore() {
    if (!restoring) return;
    var lists = document.querySelectorAll(SCROLLERS);
    restoring.inner.forEach(function (x) { if (lists[x[0]]) lists[x[0]].scrollTop = x[1]; });
    var el = document.getElementById(restoring.id);
    if (el && el.getBoundingClientRect && window.scrollTo) {
      window.scrollTo(0, Math.max(0, el.getBoundingClientRect().top + window.scrollY + restoring.y));
    }
  }
  (function () {
    if (!restoring) return;
    var moved = false;
    // The reader moving first ends the putting back (and lets their own place be kept).
    ["wheel", "touchstart", "keydown", "mousedown"].forEach(function (t) {
      window.addEventListener(t, function () {
        moved = true;
        restoring = null;
        try { history.scrollRestoration = "auto"; } catch (e) { /* not settable */ }
      }, { passive: true, once: true, capture: true });
    });
    function soon() { setTimeout(restore, 0); }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", soon); else soon();
    // Again once images and fonts are in, unless the reader has moved since.
    window.addEventListener("load", function () {
      if (moved) return;
      restore();
      try { history.scrollRestoration = "auto"; } catch (e) { /* not settable */ }
      restoring = null;
    });
  })();

  // ---- each page's sections in the sidebar ------------------------------------------------
  // Under the sidebar link to each page script#asta-sections lists, a list of links to its
  // sections, shut or open with the chevron Quarto gives a sidebar section. A click on a section
  // of a page this document already shows (the page itself, or one the feed appended) scrolls
  // to it here; any other link is followed.
  function cssId(id) { return '[id="' + String(id).replace(/["\\]/g, "\\$&") + '"]'; }
  function startSections() {
    var src = document.getElementById("asta-sections"), data = null, root;
    try { data = src && JSON.parse(src.textContent); root = new URL(data.site, FIRST).href; } catch (e) { data = null; }
    if (!data || !data.pages || typeof data.site !== "string") return null;
    var lists = [], seq = 0, shown = null;
    function entriesFor(url) {
      if (url.indexOf(root) !== 0) return null;
      var key = url.slice(root.length), alt = key;
      try { alt = decodeURIComponent(key); } catch (e) { /* as written */ }
      return data.pages[key] || data.pages[alt] || null;
    }
    function setOpen(l, on) {
      l.ul.classList.toggle("show", on);
      l.toggle.setAttribute("aria-expanded", on ? "true" : "false");
    }
    [].slice.call(document.querySelectorAll("#quarto-sidebar a.sidebar-link[href]")).forEach(function (a) {
      var url, li = a.closest && a.closest("li.sidebar-item"), box = a.parentNode;
      try { url = canon(new URL(a.getAttribute("href"), FIRST).href); } catch (e) { return; }
      var list = entriesFor(url);
      // A Quarto section (a link with pages under it) keeps its own list.
      if (!list || !list.length || !li || li.classList.contains("sidebar-item-section")) return;
      if (lists.some(function (l) { return l.url === url; })) return;
      var path = new URL(url).pathname, id = "asta-sections-" + (++seq);
      var toggle = document.createElement("a");
      toggle.className = "sidebar-item-toggle text-start asta-sections-toggle";
      toggle.setAttribute("role", "button");
      toggle.setAttribute("tabindex", "0");
      toggle.setAttribute("aria-controls", id);
      toggle.setAttribute("aria-label", "Sections of " + (a.textContent || "").trim());
      toggle.innerHTML = '<i class="bi bi-chevron-right ms-2"></i>';
      box.appendChild(toggle);
      var ul = document.createElement("ul");
      ul.id = id;
      ul.className = "collapse list-unstyled sidebar-section depth1 asta-sections";
      ul.innerHTML = list.map(function (x) {
        return '<li class="sidebar-item"><div class="sidebar-item-container"><a class="sidebar-item-text sidebar-link asta-section-link" href="' +
          esc(path + "#" + encodeURIComponent(x.id)) + '" data-asta-section="' + esc(x.id) + '"><span class="menu-text">' +
          esc(x.title) + "</span></a></div></li>";
      }).join("");
      li.classList.add("sidebar-item-section");
      li.appendChild(ul);
      var l = { url: url, a: a, toggle: toggle, ul: ul, items: [].slice.call(ul.querySelectorAll("a.asta-section-link")), auto: false };
      if (samePage(url, FIRST)) { setOpen(l, true); shown = l; l.auto = true; } else setOpen(l, false);
      function flip(ev) { ev.preventDefault(); l.auto = false; setOpen(l, !l.ul.classList.contains("show")); }
      toggle.addEventListener("click", flip);
      toggle.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") flip(ev); });
      lists.push(l);
    });
    if (!lists.length) return null;

    // The page in view: the feed's, or this page.
    function place() { return (A.flow && A.flow.place && A.flow.place()) || { url: FIRST, el: null, prefix: "" }; }
    function target(p, id) {
      return p.el ? p.el.querySelector(cssId((p.prefix || "") + id)) : document.getElementById(id);
    }
    function mark() {
      var p = place(), l = lists.filter(function (x) { return samePage(x.url, p.url); })[0] || null;
      if (l !== shown) {
        // The page in view opens; the one it follows shuts, unless the reader opened it.
        if (shown && shown.auto) { setOpen(shown, false); shown.auto = false; }
        if (l && !l.ul.classList.contains("show")) { setOpen(l, true); l.auto = true; }
        shown = l;
      }
      var line = (window.innerHeight || 800) * 0.25, on = null;
      if (l) {
        l.items.forEach(function (a) {
          var t = target(p, a.getAttribute("data-asta-section"));
          if (t && t.getBoundingClientRect().top <= line) on = a;
        });
        if (!on) on = l.items[0];
      }
      lists.forEach(function (x) {
        x.items.forEach(function (a) {
          a.classList.toggle("active", a === on);
          if (a === on) a.setAttribute("aria-current", "location"); else a.removeAttribute("aria-current");
        });
      });
      // "On this page" steps aside while it lists just what the sidebar lists for the page in view.
      var toc = document.querySelector('nav[role="doc-toc"]'), ul = toc && toc.querySelector(":scope > ul");
      if (toc) toc.classList.toggle("asta-toc-same", !!(l && ul && same(ul, l)));
    }
    // Compared by the heading ids alone: Quarto's script makes the list's "#id" links full
    // addresses (page.html#id), and an appended page's list keeps "#id".
    function same(ul, l) {
      var ids = [].slice.call(ul.querySelectorAll("a[href]")).map(function (a) {
        var h = (a.getAttribute("href") || "").split("#")[1] || "";
        try { return decodeURIComponent(h); } catch (e) { return h; }
      });
      var want = l.items.map(function (a) { return a.getAttribute("data-asta-section"); });
      return ids.length === want.length && ids.every(function (x, i) { return x === want[i]; });
    }
    document.getElementById("quarto-sidebar").addEventListener("click", function (ev) {
      var a = ev.target.closest && ev.target.closest("a.asta-section-link");
      if (!a || ev.button > 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
      var url = noHash(new URL(a.getAttribute("href"), FIRST).href), id = a.getAttribute("data-asta-section");
      var have = ((A.flow && A.flow.sections) || []).filter(function (s) { return samePage(s.url, url) && s.loaded; })[0];
      var p = have ? { url: have.url, el: have.el, prefix: have.prefix } : (samePage(url, FIRST) ? { url: FIRST, el: null } : null);
      var t = p && target(p, id);
      if (!t) return;
      ev.preventDefault();
      // The address names the section (a copied link opens there), until the reader scrolls on.
      if (A.flow && A.flow.hold) A.flow.hold();
      try { history.pushState(null, "", p.url + "#" + encodeURIComponent(id)); } catch (e) { /* a sandboxed frame may refuse */ }
      if (t.scrollIntoView) t.scrollIntoView({ block: "start" });
    });
    var ticking = false;
    function onScroll() {
      if (ticking) return;
      ticking = true;
      (window.requestAnimationFrame || setTimeout)(function () { ticking = false; mark(); });
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    window.addEventListener("load", onScroll); // again once Quarto has set up its own lists
    mark();
    return { mark: mark, lists: lists };
  }

  function start() {
    var src = document.getElementById("asta-flow");
    if (!src) return;
    var data;
    try { data = JSON.parse(src.textContent); } catch (e) { return; }
    var main = document.getElementById("quarto-document-content") || document.querySelector("main");
    if (!main || !data || typeof data.site !== "string") return;
    // The feed's pages, in the sidebar's order: its links into the site, once each.
    var root;
    try { root = new URL(data.site, FIRST).href; } catch (e) { return; }
    var pages = [], seen = {};
    [].slice.call(document.querySelectorAll("#quarto-sidebar a.sidebar-link[href]:not(.asta-section-link)")).forEach(function (a) {
      var raw = a.getAttribute("href") || "", url;
      if (!raw || raw.charAt(0) === "#") return;
      try { url = canon(new URL(raw, FIRST).href); } catch (e) { return; }
      if (url.indexOf(root) !== 0 || !/\.html$/.test(url) || seen[url]) return;
      seen[url] = true;
      pages.push({ url: url, title: (a.textContent || "").trim() || url, current: samePage(url, FIRST) });
    });
    var at = -1;
    pages.forEach(function (p, i) { if (p.current && at < 0) at = i; });
    if (at < 0) return;
    pages[at].url = FIRST;
    var rest = pages.slice(at + 1).filter(function (p) { return p.url; });

    var first = { url: FIRST, el: null, hash: location.hash, title: document.title, page: pages[at], loaded: true };
    var sections = [first], current = first, next = 0, busy = false;
    var feed = document.createElement("div");
    feed.className = "asta-flow";
    main.appendChild(feed);
    var sentinel = document.createElement("div");
    sentinel.className = "asta-flow-sentinel";
    sentinel.setAttribute("aria-hidden", "true");

    // Pages in another folder than this one: relative links resolve from the address, which
    // the feed changes, so every relative link is made absolute from the page it came from.
    var crossFolder = rest.some(function (p) { return dirOf(p.url) !== dirOf(FIRST); });
    if (crossFolder) {
      fixLinks(document.body, FIRST);
      // Quarto's search finds the site from this page's offset to its root, read against the
      // address when it is used: made a path from the root, it holds at any address.
      var off = document.querySelector('meta[name="quarto:offset"]');
      if (off) { try { off.setAttribute("content", new URL(off.getAttribute("content") || "./", FIRST).pathname); } catch (e) { /* leave it */ } }
      if (window.MutationObserver) {
        new MutationObserver(function (records) {
          records.forEach(function (r) {
            r.addedNodes.forEach(function (n) { if (n.nodeType === 1) fixLinks(n, A.pageUrl(n)); });
          });
        }).observe(main, { childList: true, subtree: true });
      }
    }

    // The sidebar's links to the flow's pages, read before the address changes.
    var sideLinks = [].slice.call(document.querySelectorAll("#quarto-sidebar a.sidebar-link[href]:not(.asta-section-link)")).map(function (a) {
      var u;
      try { u = canon(new URL(a.getAttribute("href"), FIRST).href); } catch (e) { u = null; }
      return { a: a, url: u };
    }).filter(function (x) { return pages.some(function (p) { return samePage(p.url, x.url); }); });
    function markSidebar(url) {
      sideLinks.forEach(function (x) {
        var on = samePage(x.url, url);
        x.a.classList.toggle("active", on);
        if (on) x.a.setAttribute("aria-current", "page"); else x.a.removeAttribute("aria-current");
      });
    }

    function divider(s, n) {
      return '<div class="asta-flow-divider">' +
        '<div class="asta-flow-kicker">Next <span class="asta-flow-step">' + n + " of " + pages.length + "</span></div>" +
        '<h1 class="title asta-flow-title"><a href="' + esc(s.url) + '">' + esc(s.page.title) + "</a></h1></div>";
    }

    function setStatus(s, html) {
      var st = s.el.querySelector(".asta-flow-status");
      if (!html) { if (st) st.parentNode.removeChild(st); return; }
      if (!st) {
        st = document.createElement("div");
        st.className = "asta-flow-status";
        st.setAttribute("role", "status");
        s.el.appendChild(st);
      }
      st.innerHTML = html;
    }

    function load(s) {
      busy = true;
      s.failed = false;
      setStatus(s, '<span class="asta-flow-spinner" aria-hidden="true"></span> Loading ' + esc(s.page.title) + "…");
      return fetch(s.url, { credentials: "same-origin" }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.text();
      }).then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var t = doc.querySelector("title");
        if (t && t.textContent) s.title = t.textContent;
        var assets = missingAssets(doc, s.url);
        s.toc = tocOf(doc, s.prefix);
        var box = extract(doc, s.url, s.prefix);
        if (!box) throw new Error("the page has no content");
        doc = html = null;
        return loadAssets(assets).then(function () {
          setStatus(s, "");
          s.el.appendChild(box);
          s.loaded = true;
          A.init(s.el);
          drawMermaid(s.el);
        });
      }).catch(function (e) {
        s.failed = true;
        setStatus(s, "This page could not be loaded (" + esc(e && e.message || e) + '). <button type="button" class="asta-flow-retry">Try again</button> or <a href="' +
          esc(s.url) + '">open it</a>.');
        var b = s.el.querySelector(".asta-flow-retry");
        if (b) b.addEventListener("click", function () { if (!busy) load(s).then(after); });
      }).then(function () { busy = false; });
    }

    // Mermaid diagrams (asta-workflow) on an appended page, when the runtime is on the page.
    function drawMermaid(el) {
      var nodes = [].slice.call(el.querySelectorAll("pre.mermaid:not([data-processed])"));
      if (!nodes.length || !window.mermaid || !window.mermaid.run) return;
      try { window.mermaid.run({ nodes: nodes }); } catch (e) { /* the source stays readable */ }
    }

    function endMark() {
      var end = document.createElement("div");
      end.className = "asta-flow-end";
      end.textContent = "End";
      feed.appendChild(end);
    }

    function after() {
      if (sentinel.parentNode) sentinel.parentNode.removeChild(sentinel);
      var last = sections[sections.length - 1];
      if (last.failed) return;
      if (next >= rest.length) { endMark(); return; }
      feed.appendChild(sentinel);
      watch();
    }

    function loadNext() {
      if (busy || next >= rest.length) return;
      var last = sections[sections.length - 1];
      if (last.failed || !last.loaded) return;
      var page = rest[next++];
      var n = at + 1 + next;
      var s = { url: page.url, page: page, hash: "", title: page.title, prefix: "asta-f" + n + "-", loaded: false };
      s.el = document.createElement("section");
      s.el.className = "asta-flow-page";
      s.el.setAttribute("data-asta-url", page.url);
      s.el.setAttribute("aria-label", page.title);
      s.el.innerHTML = divider(s, n);
      if (sentinel.parentNode) sentinel.parentNode.removeChild(sentinel);
      feed.appendChild(s.el);
      sections.push(s);
      load(s).then(after);
    }
    A.flow = { loadNext: loadNext, sections: sections, place: function () { return current; }, hold: function () { hold(); } };

    var io = null;
    function watch() {
      if (!window.IntersectionObserver) { check(); return; }
      if (!io) {
        // A screen before the end of what is loaded, fetch the next page.
        io = new window.IntersectionObserver(function (entries) {
          if (entries.some(function (e) { return e.isIntersecting; })) loadNext();
        }, { rootMargin: "0px 0px 100% 0px" });
      }
      io.unobserve(sentinel);
      io.observe(sentinel);
    }
    function check() {
      if (sentinel.parentNode && sentinel.getBoundingClientRect().top < window.innerHeight * 2) loadNext();
    }

    // The page in view: the last one whose top is above a quarter of the window, or, at the
    // end of the document, the last one whose top is in the window (a short last page).
    function inView() {
      var h = window.innerHeight, line = h * 0.25, cur = first;
      var atEnd = window.scrollY + h >= document.documentElement.scrollHeight - 2;
      sections.forEach(function (s) {
        if (!s.el || !s.loaded) return;
        var top = s.el.getBoundingClientRect().top;
        if (top <= line || (atEnd && top < h)) cur = s;
      });
      return cur;
    }
    // "On this page" lists the headings of the page in view: the first page's own list, or the
    // list each appended page brought with it.
    var tocEl = document.querySelector('nav[role="doc-toc"]');
    var firstToc = tocEl && tocEl.querySelector(":scope > ul");
    first.toc = firstToc;
    function showToc(s) {
      if (!tocEl) return;
      var want = s.toc || null, have = tocEl.querySelector(":scope > ul");
      if (have === want) return;
      if (have) tocEl.removeChild(have);
      if (want) tocEl.appendChild(want);
      tocEl.hidden = !want || !want.querySelector("a");
      markToc();
    }
    function markToc() {
      if (!tocEl || current === first || !current.toc) return; // the first page's: Quarto marks it
      var links = [].slice.call(current.toc.querySelectorAll("a[data-asta-target]")), on = null;
      links.forEach(function (a) {
        var t = current.el.querySelector('[id="' + a.getAttribute("data-asta-target").replace(/["\\]/g, "\\$&") + '"]');
        if (t && t.getBoundingClientRect().top <= 200) on = a;
      });
      links.forEach(function (a) { a.classList.toggle("active", a === (on || links[0])); });
    }
    if (tocEl) {
      // A heading of an appended page: scroll to it, its page's address with the heading's id.
      tocEl.addEventListener("click", function (ev) {
        var a = ev.target.closest && ev.target.closest("a[data-asta-target]");
        if (!a || current === first) return;
        var t = current.el.querySelector('[id="' + a.getAttribute("data-asta-target").replace(/["\\]/g, "\\$&") + '"]');
        if (!t) return;
        ev.preventDefault();
        hold();
        try { history.pushState(null, "", current.url + a.getAttribute("href")); } catch (e) { /* a sandboxed frame may refuse */ }
        t.scrollIntoView({ block: "start" });
      });
    }

    function switchTo(s) {
      var here = noHash(location.href);
      sections.forEach(function (x) { if (x.url === here) x.hash = location.hash; });
      current = s;
      if (here !== s.url) {
        try { history.replaceState(history.state, "", s.url + (s.hash || "")); } catch (e) { /* a sandboxed frame may refuse */ }
      }
      if (s.title) document.title = s.title;
      markSidebar(s.url);
      showToc(s);
      if (A.sidebarSections) A.sidebarSections.mark();
    }

    // The reading position of the page in view (see parsePos), or "" near its top.
    function posToken(s) {
      var scope = s.el ? s.el.querySelector(".asta-flow-content") : main;
      if (!scope) return "";
      var best = null;
      scope.querySelectorAll("section[id]").forEach(function (el) {
        if (!s.el && el.closest(".asta-flow")) return;
        if (el.getBoundingClientRect().top <= 0) best = el;
      });
      if (!best) return "";
      var id = s.el ? best.id.slice(s.prefix.length) : best.id;
      var inner = [];
      [].slice.call(scope.querySelectorAll(SCROLLERS)).filter(function (el) {
        return s.el || !el.closest(".asta-flow");
      }).forEach(function (el, i) { if (el.scrollTop > 0) inner.push(i + ":" + Math.round(el.scrollTop)); });
      return encodeURIComponent(id) + "~" + Math.round(-best.getBoundingClientRect().top) +
        (inner.length ? "~" + inner.join(".") : "");
    }
    function headingHash(s, h) {
      var id = h.slice(1);
      try { id = decodeURIComponent(id); } catch (e) { /* as written */ }
      var el = (s.el || document).querySelector('[id="' + ((s.prefix || "") + id).replace(/["\\]/g, "\\$&") + '"]');
      return !!el && (el.tagName === "SECTION" || /^H[1-6]$/.test(el.tagName));
    }
    function savePos() {
      var s = current;
      if (held || noHash(location.href) !== s.url) return;
      var h = location.hash;
      if (h && !POS.test(h) && !headingHash(s, h)) return; // a panel's anchor stays
      var tok = posToken(s), hash = tok ? "#flow-at=" + tok : "";
      if (hash === h) return;
      try { history.replaceState(history.state, "", s.url + hash); } catch (e) { return; }
      s.hash = hash;
    }
    var posTimer = null, held = false;
    // An address that names a place (a page opened at #<id>, a jump to a heading: a sidebar
    // section, "On this page" on an appended page) keeps that id, not a reading position, until
    // the reader moves on (below).
    function hold() { held = true; clearTimeout(posTimer); posTimer = null; }
    function later() {
      if (restoring) return; // not while the page puts the reader back
      clearTimeout(posTimer);
      posTimer = setTimeout(function () { posTimer = null; savePos(); }, 400);
    }
    // A panel's list scrolling inside the page: scroll events do not bubble, but are captured.
    document.addEventListener("scroll", function (ev) { if (ev.target !== document) later(); }, true);
    // Before a click or a key can take the reader elsewhere (a file link opens the Files tab), the
    // place waiting to be kept is kept now: a later address change would land on the next page.
    ["pointerdown", "keydown"].forEach(function (t) {
      window.addEventListener(t, function () {
        if (posTimer === null) return;
        clearTimeout(posTimer);
        posTimer = null;
        savePos();
      }, true);
    });
    ["wheel", "touchstart", "keydown", "mousedown"].forEach(function (t) {
      window.addEventListener(t, function () { held = false; }, { passive: true, capture: true });
    });
    var ticking = false;
    function onScroll() {
      if (!window.IntersectionObserver) check();
      if (ticking) return;
      ticking = true;
      (window.requestAnimationFrame || setTimeout)(function () {
        ticking = false;
        var s = inView();
        if (s !== current) switchTo(s);
        markToc();
      });
      later();
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });

    // A heading's link on an appended page (#tests) goes to that page's heading.
    window.addEventListener("hashchange", function () {
      if (location.hash && !POS.test(location.hash)) hold();
      var here = noHash(location.href), h = "";
      try { h = decodeURIComponent(location.hash.slice(1)); } catch (e) { h = ""; }
      if (!h) return;
      sections.forEach(function (s) {
        if (!s.el || s.url !== here) return;
        var t = s.el.querySelector('[id="' + (s.prefix + h).replace(/["\\]/g, "\\$&") + '"]');
        if (t && t.scrollIntoView) t.scrollIntoView({ block: "start" });
      });
    });

    if (!rest.length) endMark(); else { feed.appendChild(sentinel); watch(); }
    if (location.hash && !POS.test(location.hash)) hold(); // opened at a place: its id stays
    if (window.scrollY > 0) later(); // scrolled before this script was ready
  }

  A.flow = { loadNext: function () {}, sections: [] };
  A.startFlow = start;
  function boot() {
    A.sidebarSections = startSections();
    start();
    if (A.sidebarSections) A.sidebarSections.mark();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
