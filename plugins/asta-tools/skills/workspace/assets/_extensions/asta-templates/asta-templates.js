/* asta-templates core: what the widget scripts share, the cards links open, and each page's
   sections in the sidebar.

   Widgets. Each widget script (theories.js, tests.js, autods.js, literature.js) adds its start
   function to AstaTemplates.widgets; start(scope) draws the panels in scope that are not drawn yet.
   AstaTemplates.init(scope) runs them all (tests first, which the theories' Tests tab links to).

   Sections. Under each sidebar link to a page, that page's sections (script#asta-sections,
   written by asta-templates.lua: its level-2 headings and their ids), folded with Quarto's chevron:
   the page the reader is on open, the others shut. The section in view is marked as the reader
   scrolls. "On this page" is hidden while it lists exactly those sections, and shows when it has
   more (a page's subsections). Uses no browser storage. */
(function () {
  "use strict";

  var A = window.AstaTemplates = window.AstaTemplates || {};
  A.widgets = A.widgets || [];
  if (A.cards) return; // loaded once

  function noHash(u) { return String(u || "").split("#")[0]; }
  // A page's address: a folder's is its index.html (Quarto links the front page as the site's
  // root, "./").
  function canon(u) { u = noHash(u); return /\/$/.test(u) ? u + "index.html" : u; }
  function samePage(a, b) { return canon(a) === canon(b); }
  var HERE = noHash(location.href);

  A.init = function (scope) {
    A.widgets.slice().sort(function (a, b) { return (a.order || 0) - (b.order || 0); }).forEach(function (w) {
      try { w.start(scope || document); } catch (e) { if (window.console) console.error(e); }
    });
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  // A link from the data: a script URL (javascript:, vbscript:, data:) becomes "#", so a
  // crafted run or paper file can't run code when its link is clicked.
  function escUrl(s) {
    var u = String(s == null ? "" : s);
    return esc(/^(javascript|vbscript|data):/i.test(u.replace(/[\u0000-\u0020\u007f]+/g, "")) ? "#" : u);
  }

  // ---- cards -------------------------------------------------------------------------------
  // A link that autolink.lua gave a card (a test, a theory, a gap, an experiment, a figure, a
  // paper or dataset or site, a citation, an evidence claim, a workspace file) names it in
  // data-asta-card: a key into the page's cards (script.asta-cards-data). Every card is the same
  // kind of thing, drawn here the same way: sections, each with any of a role, a title (linked), a sub line, a thumbnail, a quote, text
  // clamped to some lines, a test's verdict, tests' verdicts, a tally of verdicts, facts and
  // links; then a footer. Hovering the link, focusing it or tapping it opens its card beside
  // it (never over it); the card stays while the pointer is on it; Esc, a click elsewhere, or
  // the pointer leaving both for a moment closes it. The link's own hover (Quarto's reference
  // and cross-reference previews, a native title, the evidence popover) gives way to it.
  A.cards = (function () {
    var card = null, owner = null, openTimer = 0, closeTimer = 0, touch = false, seq = 0, quiet = null;
    var store = null;
    function mention(el) { return el && el.closest ? el.closest("[data-asta-card]") : null; }
    function inCard(el) { return !!(card && el && card.contains(el)); }
    function urlFor(a, href) {
      try { return new URL(href, HERE).href; } catch (e) { return href; }
    }
    // The card a link names: from the page's store (or, written whole, the attribute itself).
    function spec(a) {
      var key = a.getAttribute("data-asta-card") || "";
      if (key.charAt(0) === "{") { try { return JSON.parse(key); } catch (e) { return null; } }
      var el = document.querySelector("script.asta-cards-data");
      if (!el) return null;
      if (!store || store.el !== el) {
        var data = {};
        try { data = JSON.parse(el.textContent) || {}; } catch (e) { data = {}; }
        store = { el: el, data: data };
      }
      return store.data[key] || null;
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
        h += s.href ? '<a class="ap-al-go ap-al-clamp" href="' + escUrl(urlFor(a, s.href)) + '"' +
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
          return '<a href="' + escUrl(urlFor(a, l.href)) + '"' + (l.external ? ' target="_blank" rel="noopener"' : "") + ">" +
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
    // draws with CSS and which html.asta-cards hides (asta-templates.css) where a card stands in.
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

  // ---- each page's sections in the sidebar ------------------------------------------------
  // Under the sidebar link to each page script#asta-sections lists, a list of links to its
  // sections, shut or open with the chevron Quarto gives a sidebar section. A click on a section
  // of this page scrolls to it here; a section of another page is an ordinary link.
  function startSections() {
    var src = document.getElementById("asta-sections"), data = null, root;
    try { data = src && JSON.parse(src.textContent); root = new URL(data.site, HERE).href; } catch (e) { data = null; }
    if (!data || !data.pages || typeof data.site !== "string") return null;
    var lists = [], seq = 0, here = null;
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
      try { url = canon(new URL(a.getAttribute("href"), HERE).href); } catch (e) { return; }
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
      var l = { url: url, a: a, toggle: toggle, ul: ul, items: [].slice.call(ul.querySelectorAll("a.asta-section-link")) };
      if (samePage(url, HERE)) here = l;
      setOpen(l, l === here);
      function flip(ev) { ev.preventDefault(); setOpen(l, !l.ul.classList.contains("show")); }
      toggle.addEventListener("click", flip);
      toggle.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") flip(ev); });
      lists.push(l);
    });
    if (!lists.length) return null;

    // This page's section in view: the last one whose top is above a quarter of the window.
    function mark() {
      var line = (window.innerHeight || 800) * 0.25, on = null;
      if (here) {
        here.items.forEach(function (a) {
          var t = document.getElementById(a.getAttribute("data-asta-section"));
          if (t && t.getBoundingClientRect().top <= line) on = a;
        });
        if (!on) on = here.items[0];
      }
      lists.forEach(function (x) {
        x.items.forEach(function (a) {
          a.classList.toggle("active", a === on);
          if (a === on) a.setAttribute("aria-current", "location"); else a.removeAttribute("aria-current");
        });
      });
      // "On this page" steps aside while it lists just what the sidebar lists for this page.
      var toc = document.querySelector('nav[role="doc-toc"]'), ul = toc && toc.querySelector(":scope > ul");
      if (toc) toc.classList.toggle("asta-toc-same", !!(here && ul && same(ul, here)));
    }
    // Compared by the heading ids alone: Quarto's script makes the list's "#id" links full
    // addresses (page.html#id).
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
      var id = a.getAttribute("data-asta-section"), t = document.getElementById(id);
      if (!samePage(new URL(a.getAttribute("href"), HERE).href, HERE) || !t) return;
      ev.preventDefault();
      // The address names the section (a copied link opens there).
      try { history.pushState(null, "", HERE + "#" + encodeURIComponent(id)); } catch (e) { /* a sandboxed frame may refuse */ }
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
  function boot() { A.sidebarSections = startSections(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
