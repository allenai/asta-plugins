#!/usr/bin/env python3
"""Review a Quarto reveal.js deck's changes as rendered slides.

Used by what-changed.py (``--render-decks DIR``): each new, changed or removed
slide is rendered as the deck shows it, with changed words marked on the slide,
and the deck's What changed section becomes a view with three modes: Changes
marked, Clean, and Before / after. Unchanged slides around a change are folded
into a count, like a code diff's context.

A slide is changed when its markup differs or, with the same markup, when its
rendered image differs (an image swapped, a style fix). Slides are matched by
what-changed.py's ``match_slides``, so "Slide N" is the number the deck shows.

Needs Python Playwright with Chromium (``pip install playwright`` and
``python -m playwright install --with-deps chromium``).
"""

import hashlib
import html
import json
import os
import re
import shutil
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

VIEWPORT = {"width": 1600, "height": 900}
CONTEXT = 2  # unchanged slides shown, folded, before and after each change

# Reveal.getSlides() is in document order, the order reveal_slides() reads.
LIST_JS = """() => Reveal.getSlides().map((s) => {
  const w = document.createTreeWalker(s, NodeFilter.SHOW_TEXT); const p = []; let n;
  while ((n = w.nextNode())) p.push(n.textContent);
  return p.join(' ').replace(/\\s+/g, ' ').trim();
})"""

GOTO_JS = """(i) => {
  const x = Reveal.getIndices(Reveal.getSlides()[i]);
  Reveal.slide(x.h, x.v || 0, Infinity);
  Reveal.layout();
}"""

MARK_CSS = (
    ".dr-ins{background:rgba(47,191,113,.3);color:inherit;text-decoration:none;border-radius:.15em;padding:0 .06em}"
    ".dr-del{background:rgba(253,70,69,.28);color:inherit;border-radius:.15em;padding:0 .06em;text-decoration-thickness:.08em}"
    ".dr-frame{position:fixed;inset:0;pointer-events:none;z-index:99;border:6px solid var(--dr-c)}"
    ".dr-badge{position:fixed;right:24px;top:20px;z-index:100;background:var(--dr-c);color:#04140f;"
    "font:700 22px/1 system-ui,sans-serif;padding:8px 14px;border-radius:8px}"
)

FRAME_JS = """([css, color, label]) => {
  const st = document.createElement('style'); st.textContent = css; document.head.append(st);
  const f = document.createElement('div'); f.className = 'dr-frame'; f.style.setProperty('--dr-c', color);
  const b = document.createElement('div'); b.className = 'dr-badge'; b.style.setProperty('--dr-c', color);
  b.textContent = label; document.body.append(f, b);
}"""

# Marks, in the current slide's text nodes, the words that differ from the old slide's words.
MARK_WORDS_JS = """([css, old]) => {
  const st = document.createElement('style'); st.textContent = css; document.head.append(st);
  const s = Reveal.getCurrentSlide(); const w = document.createTreeWalker(s, NodeFilter.SHOW_TEXT);
  const nodes = []; let n; while ((n = w.nextNode())) if (n.textContent.trim()) nodes.push(n);
  const b = []; nodes.forEach((nd) => nd.textContent.split(/(\\s+)/).forEach((t) => { if (t.trim()) b.push(t); }));
  const a = old, m = a.length, q = b.length;
  const L = Array.from({ length: m + 1 }, () => new Int32Array(q + 1));
  for (let i = m - 1; i >= 0; i--) for (let j = q - 1; j >= 0; j--)
    L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const keep = new Set(), dels = {}; let i = 0, j = 0;
  while (i < m && j < q) {
    if (a[i] === b[j]) { keep.add(j); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) { (dels[j] = dels[j] || []).push(a[i]); i++; }
    else j++;
  }
  while (i < m) { (dels[q] = dels[q] || []).push(a[i]); i++; }
  const del = (t) => { const d = document.createElement('del'); d.className = 'dr-del'; d.textContent = t; return d; };
  let idx = 0;
  nodes.forEach((nd, k) => {
    const frag = document.createDocumentFragment();
    nd.textContent.split(/(\\s+)/).forEach((t) => {
      if (!t.trim()) { frag.append(t); return; }
      if (dels[idx]) frag.append(del(dels[idx].join(' ')), ' ');
      if (keep.has(idx)) frag.append(t);
      else { const e = document.createElement('ins'); e.className = 'dr-ins'; e.textContent = t; frag.append(e); }
      idx++;
    });
    if (k === nodes.length - 1 && dels[q]) frag.append(' ', del(dels[q].join(' ')));
    nd.replaceWith(frag);
  });
  Reveal.layout();
}"""


def _serve(root):
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=root))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Renderer:
    """One Chromium and one local server for both sites; a page per deck side."""

    def __init__(self, old_root, new_root):
        from playwright.sync_api import sync_playwright

        self._tmp = tempfile.mkdtemp(prefix="deck-review-")
        os.symlink(os.path.abspath(old_root), os.path.join(self._tmp, "old"))
        os.symlink(os.path.abspath(new_root), os.path.join(self._tmp, "new"))
        self._server = _serve(self._tmp)
        self._base = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._pages = {}

    def close(self):
        try:
            self._browser.close()
            self._pw.stop()
        finally:
            self._server.shutdown()
            shutil.rmtree(self._tmp, ignore_errors=True)

    def _open(self, side, deck):
        page = self._browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        page.goto(f"{self._base}/{side}/{quote(deck)}")
        page.wait_for_function(
            "() => window.Reveal && Reveal.isReady && Reveal.isReady()", timeout=30000
        )
        page.evaluate(
            "() => Reveal.configure({transition: 'none', backgroundTransition: 'none'})"
        )
        page.evaluate("() => document.fonts.ready")
        return page

    def page(self, side, deck):
        key = (side, deck)
        if key not in self._pages:
            self._pages[key] = self._open(side, deck)
        return self._pages[key]

    def texts(self, side, deck):
        return self.page(side, deck).evaluate(LIST_JS)

    def shoot(self, side, deck, index, path=None, mark=None):
        """Screenshot slide ``index``; ``mark`` is (js, arg) applied on a fresh page."""
        page = self._open(side, deck) if mark else self.page(side, deck)
        try:
            page.evaluate(GOTO_JS, index)
            if mark:
                page.evaluate(*mark)
            page.evaluate("""async () => {
              const images = [...Reveal.getCurrentSlide().querySelectorAll('img')];
              await Promise.all(images.map(i => i.decode().catch(() => {})));
              await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            }""")
            page.wait_for_timeout(50)
            data = page.screenshot(type="png")
        finally:
            if mark:
                page.close()
        if path:
            with open(path, "wb") as f:
                f.write(data)
        return data


def classify(old, new, pairs, same_image=None):
    """Rows in deck order as (kind, new_index, old_index), and removed old indices.

    ``same_image(old_index, new_index)`` decides markup-equal slides; without it
    they count as unchanged.
    """
    rows = []
    for index in range(len(new)):
        before = pairs.get(index)
        if before is None:
            rows.append(("new", index, None))
        elif old[before]["body"] != new[index]["body"]:
            rows.append(("changed", index, before))
        elif same_image is not None and not same_image(before, index):
            rows.append(("look", index, before))
        else:
            rows.append(("unchanged", index, before))
    removed = [index for index in range(len(old)) if index not in pairs.values()]
    return rows, removed


def context(rows, width=CONTEXT):
    """Indices of rows to show: every change and ``width`` rows on each side."""
    show = set()
    for k, (kind, _, _) in enumerate(rows):
        if kind != "unchanged":
            show.update(range(max(0, k - width), min(len(rows), k + width + 1)))
    return sorted(show)


def slide_title(slide):
    match = re.search(r"<h[12][^>]*>(.*?)</h[12]>", slide["body"], re.S)
    text = re.sub(r"<[^>]+>", "", match.group(1)) if match else ""
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def review(deck, link, img_dir, img_url, old, new, pairs, renderer):
    """Render a deck's changes; return the view's HTML, or None if nothing changed.

    ``old`` is empty for a new deck; ``new`` is never empty here.
    """
    os.makedirs(img_dir, exist_ok=True)
    digest = {}

    def shot(side, index):
        if (side, index) not in digest:
            data = renderer.shoot(side, deck, index)
            digest[side, index] = hashlib.sha256(data).hexdigest()
        return digest[side, index]

    rows, removed = classify(
        old,
        new,
        pairs,
        (lambda o, n: shot("old", o) == shot("new", n)) if old else None,
    )
    shown = context(rows)
    if not removed and all(rows[k][0] == "unchanged" for k in shown):
        return None
    old_text = renderer.texts("old", deck) if old else []
    items = []
    for k in shown:
        kind, n, o = rows[k]
        name = f"s{n + 1}"
        renderer.shoot("new", deck, n, os.path.join(img_dir, name + ".png"))
        item = {
            "n": n + 1,
            "kind": kind,
            "title": slide_title(new[n]),
            "clean": f"{img_url}/{name}.png",
            "link": link + "#/" + new[n]["anchor"],
        }
        mark = None
        if kind == "new":
            mark = (FRAME_JS, [MARK_CSS, "#2fbf71", "New slide"])
        elif kind == "changed":
            mark = (MARK_WORDS_JS, [MARK_CSS, old_text[o].split()])
        if mark:
            renderer.shoot("new", deck, n, os.path.join(img_dir, name + "-m.png"), mark)
            item["marked"] = f"{img_url}/{name}-m.png"
        if kind in {"changed", "look"}:
            renderer.shoot("old", deck, o, os.path.join(img_dir, name + "-b.png"))
            item["before"] = f"{img_url}/{name}-b.png"
        items.append(item)
    gone = []
    for o in removed:
        name = f"r{o + 1}"
        mark = (FRAME_JS, [MARK_CSS, "#fd4645", "Removed"])
        renderer.shoot("old", deck, o, os.path.join(img_dir, name + ".png"), mark)
        gone.append(
            {"n": o + 1, "title": slide_title(old[o]), "img": f"{img_url}/{name}.png"}
        )
    return view(items, gone, len(new))


def view(items, removed, total):
    data = json.dumps({"items": items, "removed": removed, "total": total})
    return VIEW.replace("__DATA__", data.replace("</", "<\\/"))


# Scoped to its own container so several decks can share one What changed page;
# STYLE and SCRIPT go on the page once.
VIEW = """<div class="deck-review">
<div class="dr-bar"><span class="dr-count"></span>
<span class="dr-seg" role="group" aria-label="Slide view"><button type="button" data-v="marked" aria-pressed="true">Changes marked</button><button type="button" data-v="clean" aria-pressed="false">Clean</button><button type="button" data-v="before" aria-pressed="false">Before / after</button></span></div>
<div class="dr-list"></div>
<script type="application/json" class="dr-data">__DATA__</script>
</div>"""

STYLE = """<style>
.deck-review .dr-bar{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:.5rem 0}
.deck-review .dr-count{opacity:.75}
.deck-review .dr-seg{margin-left:auto;display:inline-flex;border:1px solid rgba(127,127,127,.6);border-radius:8px;overflow:hidden}
.deck-review .dr-seg button{font:inherit;background:none;color:inherit;border:0;padding:4px 12px;cursor:pointer;opacity:.7}
.deck-review .dr-seg button[aria-pressed=true]{background:rgba(127,127,127,.3);font-weight:600;opacity:1}
.deck-review .dr-slide{margin:14px 0}
.deck-review .dr-slide h3{font-size:1rem;margin:0 0 6px}
.deck-review .dr-slide img{width:100%;display:block;border:1px solid rgba(127,127,127,.4);border-radius:6px}
.deck-review .dr-pair{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.deck-review .dr-pair figure{margin:0}.deck-review .dr-pair figcaption{font-size:.8rem;opacity:.75}
.deck-review .dr-more{font:inherit;font-size:.9rem;background:none;color:inherit;border:1px dashed rgba(127,127,127,.6);border-radius:6px;padding:6px 12px;cursor:pointer;display:block;width:100%;text-align:left;margin:8px 0}
.deck-review .dr-unchanged h3{opacity:.7}
.deck-review [hidden]{display:none!important}
</style>"""

SCRIPT = """<script>
document.querySelectorAll('.deck-review').forEach((root) => {
  const D = JSON.parse(root.querySelector('.dr-data').textContent);
  const list = root.querySelector('.dr-list');
  const n = (k) => D.items.filter((i) => i.kind === k).length;
  const parts = [[n('changed') + n('look'), 'changed'], [n('new'), 'new'], [D.removed.length, 'removed']]
    .filter(([c]) => c).map(([c, w]) => c + ' ' + w);
  root.querySelector('.dr-count').textContent = parts.join(', ') + ', of ' + D.total + ' slides';
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const img = (src) => { const i = el('img'); i.src = src; i.alt = ''; i.loading = 'lazy'; return i; };
  const label = { new: 'new', changed: 'changed', look: 'changed look', removed: 'removed' };
  const card = (i) => {
    const s = el('section', 'dr-slide dr-' + i.kind);
    const h = el('h3'); const a = el('a', null, 'Slide ' + i.n + (i.title ? ': ' + i.title : '')); a.href = i.link; h.append(a);
    if (label[i.kind]) h.append(' ', el('span', 'tag ' + (i.kind === 'look' ? 'changed' : i.kind), label[i.kind]));
    const one = img(i.marked || i.clean); one.dataset.clean = i.clean; one.dataset.marked = i.marked || i.clean;
    s.append(h, one);
    if (i.before) {
      const p = el('div', 'dr-pair'); p.hidden = true;
      [['Before', i.before], ['After', i.clean]].forEach(([c, src]) => { const f = el('figure'); f.append(el('figcaption', null, c), img(src)); p.append(f); });
      s.append(p);
    }
    return s;
  };
  let run = [];
  const flush = () => {
    if (!run.length) return;
    const r = run; run = [];
    const b = el('button', 'dr-more', '⋯ ' + r.length + ' unchanged slide' + (r.length > 1 ? 's' : '') + ' (' + r[0].n + (r.length > 1 ? '–' + r[r.length - 1].n : '') + ')');
    b.type = 'button'; b.setAttribute('aria-expanded', 'false');
    const box = el('div'); box.hidden = true; r.forEach((i) => box.append(card(i)));
    b.onclick = () => { box.hidden = !box.hidden; b.setAttribute('aria-expanded', String(!box.hidden)); };
    list.append(b, box);
  };
  for (const i of D.items) {
    if (i.kind === 'unchanged') { if (run.length && i.n !== run[run.length - 1].n + 1) flush(); run.push(i); continue; }
    flush(); list.append(card(i));
  }
  flush();
  for (const r of D.removed) {
    const s = el('section', 'dr-slide dr-removed'); const h = el('h3', null, 'Slide ' + r.n + ' of the old deck' + (r.title ? ': ' + r.title : '') + ' ');
    h.append(el('span', 'tag removed', 'removed')); s.append(h, img(r.img)); list.append(s);
  }
  const set = (v) => {
    root.querySelectorAll('.dr-seg button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === v)));
    root.querySelectorAll('img[data-clean]').forEach((im) => {
      im.src = v === 'clean' ? im.dataset.clean : im.dataset.marked;
      const p = im.parentElement.querySelector('.dr-pair');
      if (p) { p.hidden = v !== 'before'; im.hidden = v === 'before'; }
    });
  };
  root.querySelectorAll('.dr-seg button').forEach((b) => { b.onclick = () => set(b.dataset.v); });
});
</script>"""
