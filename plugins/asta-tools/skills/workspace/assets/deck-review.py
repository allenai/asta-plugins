#!/usr/bin/env python3
"""Review a Quarto reveal.js deck's changes as rendered slides.

Used by what-changed.py (``--render-decks DIR``): each new, changed or removed
slide is rendered as the deck shows it, with changed words marked on the slide,
and the deck's What changed section becomes a view with three modes: Changes
marked, Clean, and Before / after. Every unchanged run is folded into an
expandable count. Static screenshots are compared exactly; animated GIFs, canvas
and time-dependent custom scripts may produce extra visual-change cards.

A slide is changed when its markup differs or, with the same markup, when its
rendered image differs (an image swapped, a style fix). That image comparison
is skipped only when ``Renderer.same_static`` proves nothing that could change the
pixels differs; anything else is still compared as pixels. Slides are matched by
what-changed.py's ``match_slides``, so "Slide N" is the number the deck shows.

The workspace CLI provisions pinned Playwright and Chromium lazily through uv.
"""

import html
import json
import os
import posixpath
import re
import threading
from contextlib import ExitStack
from functools import partial
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlsplit

VIEWPORT = {"width": 1600, "height": 900}
# Displayed slides are 2x so they stay sharp on high-density screens; the
# comparison shots stay 1x (``scale="css"``), which is all equality needs.
DISPLAY_SCALE = 2

# Keep the token streams identical, excluding speaker-only and non-HTML content.
TEXT_FILTER_JS = """const visibleText = (s) => {
  const w = document.createTreeWalker(s, NodeFilter.SHOW_TEXT, {
    acceptNode: n => n.parentElement.closest('.notes, script, style, svg, math')
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT
  });
  const nodes = []; let n;
  while ((n = w.nextNode())) if (n.textContent.trim()) nodes.push(n);
  return nodes;
};
// What the audience reads on the current slide: asta-slides' section line, drawn
// outside the slide's own HTML, and then the slide.
const shownText = (s) => {
  const line = document.querySelector('.reveal .asta-slides-section');
  const head = line && !line.hidden && getComputedStyle(line).display !== 'none' ? visibleText(line) : [];
  return head.concat(visibleText(s));
};"""

LIST_JS = (
    "() => {"
    + TEXT_FILTER_JS
    + """
  // Visit each slide so slide-dependent chrome (the section line) shows its own state.
  const texts = Reveal.getSlides().map(s => {
    const x = Reveal.getIndices(s);
    Reveal.slide(x.h, x.v || 0, Infinity);
    return shownText(s).map(n => n.textContent).join(' ').replace(/\\s+/g, ' ').trim();
  });
  Reveal.slide(0, 0, 0);
  return texts;
}"""
)

# Compare the audience-facing destinations and controls, not only their pixels.
# Keep raw attributes (not resolved URLs, whose local origins differ by side).
INTERACTIONS_JS = r"""() => Reveal.getSlides().map(s => {
  const x = Reveal.getIndices(s); Reveal.slide(x.h, x.v || 0, Infinity);
  return [...s.querySelectorAll('a, area, button, input, select, textarea, form, details, summary, [role], [tabindex], [onclick]')]
    .filter(el => !el.closest('.notes') && el.checkVisibility({visibilityProperty: true}))
    .map(el => ({
      element: el.tagName.toLowerCase(),
      label: (el.getAttribute('aria-label') || el.textContent).replace(/\s+/g, ' ').trim(),
      attributes: Object.fromEntries([...el.attributes]
        .filter(a => /^(href|target|download|rel|action|method|type|name|value|disabled|checked|selected|multiple|required|readonly|open|title|role|tabindex|on\w+|aria-[\w-]+|data-[\w-]+)$/.test(a.name))
        .sort((a, b) => a.name.localeCompare(b.name)).map(a => [a.name, a.value]))
    }));
})"""

# Stable screenshots compare slide content, not index-dependent presentation chrome.
CAPTURE_CSS = """
*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }
.progress, .slide-number, .controls { visibility: hidden !important; }
"""

# Display shots show the new deck's own slide number again, unmarked, where the deck shows it.
NUMBER_JS = """(on) => {
  document.getElementById('dr-number')?.remove();
  if (!on) { Reveal.configure({slideNumber: false}); return; }
  if (!window.__drSlideNumber) return;
  const st = document.createElement('style'); st.id = 'dr-number';
  st.textContent = '.slide-number { visibility: visible !important; }';
  document.head.append(st); Reveal.configure({slideNumber: window.__drSlideNumber});
}"""

READY_JS = r"""() => Promise.race([(async () => {
  await document.fonts.ready;
  if (window.MathJax && MathJax.startup && MathJax.startup.promise) await MathJax.startup.promise;
  if (window.MathJax && MathJax.Hub) await new Promise(resolve => MathJax.Hub.Queue(resolve));
  const slide = window.Reveal && Reveal.isReady() ? Reveal.getCurrentSlide() : document.body;
  const indices = window.Reveal && Reveal.isReady() ? Reveal.getIndices(slide) : null;
  const background = indices ? Reveal.getSlideBackground(indices.h, indices.v) : null;
  const roots = [slide, background].filter(Boolean);
  for (const svg of roots.flatMap(root => [...root.querySelectorAll('svg')])) {
    if (svg.pauseAnimations) { svg.pauseAnimations(); svg.setCurrentTime(0); }
  }
  await Promise.all(roots.flatMap(root => [...root.querySelectorAll('img')]).map(async i => {
    if (i.dataset.src && !i.getAttribute('src')) i.src = i.dataset.src;
    await i.decode().catch(() => {});
  }));
  const urls = roots.flatMap(root => [root, ...root.querySelectorAll('*')]).flatMap(el => {
    const value = getComputedStyle(el).backgroundImage;
    return [...value.matchAll(/url\((?:["']?)(.*?)(?:["']?)\)/g)].map(m => m[1]);
  });
  await Promise.all(urls.map(src => new Promise(resolve => {
    const i = new Image(); i.onload = resolve; i.onerror = resolve; i.src = src;
  })));
  for (const video of roots.flatMap(root => [...root.querySelectorAll('video')])) {
    video.pause();
  }
  // Missing or stalled media stays visible as missing media, not a deck-wide failure.
  const mediaWait = (video, event, start) => new Promise(resolve => {
    const done = () => {
      clearTimeout(timer); video.removeEventListener(event, done);
      video.removeEventListener('error', done); resolve();
    };
    const timer = setTimeout(done, 1000);
    video.addEventListener(event, done, {once:true});
    video.addEventListener('error', done, {once:true});
    try { start(); } catch { done(); }
  });
  await Promise.all(roots.flatMap(root => [...root.querySelectorAll('video')]).map(async video => {
    if (video.readyState < 2 && !video.error) await mediaWait(video, 'loadeddata', () => video.load());
    if (video.readyState >= 2 && video.currentTime !== 0)
      await mediaWait(video, 'seeked', () => { video.currentTime = 0; });
  }));
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
})(), new Promise((_, reject) => setTimeout(() => reject(new Error("Slide media did not settle")), 15000))])"""

# Each visible word's box as viewport fractions, so the view can lay
# transparent, selectable text over the slide image.
WORDS_JS = (
    "() => {"
    + TEXT_FILTER_JS
    + """
  const W = innerWidth, H = innerHeight, out = [];
  for (const nd of shownText(Reveal.getCurrentSlide())) {
    if (!nd.parentElement.checkVisibility({visibilityProperty: true, opacityProperty: true})) continue;
    const re = /\\S+/g; let m;
    while ((m = re.exec(nd.textContent))) {
      const r = document.createRange(); r.setStart(nd, m.index); r.setEnd(nd, m.index + m[0].length);
      const b = r.getBoundingClientRect();
      if (b.width < 1 || b.height < 1 || b.right <= 0 || b.bottom <= 0 || b.left >= W || b.top >= H) continue;
      const f = (v) => Math.round(v * 1e4) / 1e4;
      out.push([m[0], f(b.left / W), f(b.top / H), f(b.width / W), f(b.height / H)]);
    }
  }
  return out;
}"""
)

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
MARK_WORDS_JS = (
    "([css, old]) => {"
    + TEXT_FILTER_JS
    + """
  const st = document.createElement('style'); st.textContent = css; document.head.append(st);
  const slide = Reveal.getCurrentSlide(), own = visibleText(slide).length;
  const nodes = shownText(slide);
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
    // Trailing deletions belong on the slide, never in the section line before it.
    if (own && k === nodes.length - 1 && dels[q]) frag.append(' ', del(dels[q].join(' ')));
    nd.replaceWith(frag);
  });
  if (!own && dels[q]) slide.append(del(dels[q].join(' ')));
  Reveal.layout();
}"""
)


def _serve(root):
    root = os.path.realpath(root)

    class Quiet(SimpleHTTPRequestHandler):
        def send_head(self):
            target = os.path.realpath(self.translate_path(self.path))
            if os.path.commonpath([root, target]) != root:
                self.send_error(403, "Path outside site")
                return None
            return super().send_head()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=root))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# Slide content whose pixels can change without its markup or files changing.
LIVE_RE = re.compile(
    r"<(?:script|iframe|canvas|video|audio|object|embed)\b|data-background-(?:iframe|video)",
    re.I,
)


class ResourceRefs(HTMLParser):
    """Loaded resources, excluding outbound links and entire inline data URLs."""

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.refs = []
        self.feed(source)
        self.refs.extend(re.findall(r"url\(\s*[\"']?([^\"')]+)", source, re.I))
        self.refs.extend(re.findall(r"@import\s+[\"']([^\"']+)", source, re.I))

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if not value or (tag == "a" and name == "href"):
                continue
            if name in {
                "src",
                "href",
                "poster",
                "data-src",
                "data-background",
                "data-background-image",
            }:
                self.refs.append(value)
            elif name == "srcset":
                # Data contains commas: never split its payload into fake files.
                # Mixed data/resource srcsets remain conservative.
                if "data:" in value:
                    self.refs.append("asta-unresolved-srcset:")
                else:
                    self.refs.extend(
                        part.strip().split()[0]
                        for part in value.split(",")
                        if part.strip()
                    )

    handle_startendtag = handle_starttag


def _local_paths(source, base):
    """Site paths ``source`` loads relative to ``base``, or None for a remote file."""
    paths = set()
    for link in ResourceRefs(source).refs:
        link = html.unescape(link.strip())
        parts = urlsplit(link)
        if not link or link.startswith("#") or parts.scheme == "data":
            continue
        if parts.scheme or parts.netloc:
            return None
        paths.add(posixpath.normpath(posixpath.join(base, unquote(parts.path))))
    return paths


def _same_static(files, loaded, deck, before, after):
    if (
        before.get("raw") is None
        or before["raw"] != after.get("raw")
        or before.get("position") != after.get("position")
        or before.get("frame") != after.get("frame")
        or LIVE_RE.search(after["raw"])
    ):
        return False
    # The deck documents themselves are compared as raw slides and frame.
    paths = set(loaded.get(deck, set())) - {"/" + deck}
    refs = _local_paths(after["raw"], "/" + posixpath.dirname(deck))
    if refs is None:
        return False
    return all(files._same_file(path) for path in paths | refs)


class Renderer:
    """One Chromium and an origin per site; root-relative assets retain their meaning."""

    def __init__(self, old_root, new_root):
        from playwright.sync_api import sync_playwright

        self._resources = ExitStack()
        self._bases = {}
        self._pages = {}
        self._roots = {
            "old": os.path.abspath(old_root),
            "new": os.path.abspath(new_root),
        }
        self._loaded = {}
        self._same_files = {}
        try:
            for side, root in (("old", old_root), ("new", new_root)):
                server = _serve(os.path.abspath(root))
                self._resources.callback(server.server_close)
                self._resources.callback(server.shutdown)
                self._bases[side] = f"http://127.0.0.1:{server.server_address[1]}"
            self._pw = sync_playwright().start()
            self._resources.callback(self._pw.stop)
            self._browser = self._pw.chromium.launch(
                args=[
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    "--dns-prefetch-disable",
                ]
            )
            self._resources.callback(self._browser.close)
        except Exception:
            self.close()
            raise

    def close(self):
        self._resources.close()

    def _open(self, side, deck):
        page = self._browser.new_page(
            viewport=VIEWPORT,
            device_scale_factor=DISPLAY_SCALE,
            service_workers="block",
        )
        try:
            # PR-authored documents may request only these two isolated site origins.
            page.context.route("**/*", lambda route: self._route(route, deck))
            page.context.route_web_socket("**/*", lambda socket: socket.close())
            page.set_default_timeout(30000)
            page.goto(
                f"{self._bases[side]}/{quote(deck)}", wait_until="domcontentloaded"
            )
            page.wait_for_function(
                "() => window.Reveal && Reveal.isReady && Reveal.isReady()",
                timeout=30000,
            )
            page.evaluate(
                "() => { window.__drSlideNumber = Reveal.getConfig().slideNumber; }"
            )
            page.evaluate(
                "() => Reveal.configure({transition: 'none', backgroundTransition: 'none', progress: false, slideNumber: false, controls: false, autoSlide: 0})"
            )
            page.add_style_tag(content=CAPTURE_CSS)
            page.evaluate(READY_JS)
        except Exception:
            page.close()
            raise
        return page

    def _route(self, route, deck=None):
        url = urlsplit(route.request.url)
        origin = f"{url.scheme}://{url.netloc}"
        if origin in self._bases.values():
            self._loaded.setdefault(deck, set()).add(unquote(url.path))
            route.continue_()
        else:
            route.abort()

    def page(self, side, deck):
        key = (side, deck)
        if key not in self._pages:
            self._pages[key] = self._open(side, deck)
        return self._pages[key]

    def release_deck(self, deck):
        """Keep Chromium, but release both documents before reviewing another deck."""
        for side in ("old", "new"):
            page = self._pages.pop((side, deck), None)
            if page is not None:
                page.close()

    def _same_file(self, path):
        if path not in self._same_files:
            data = []
            for side in ("old", "new"):
                target = os.path.join(self._roots[side], path.lstrip("/"))
                if os.path.isdir(target):
                    target = os.path.join(target, "index.html")
                try:
                    with open(target, "rb") as f:
                        data.append(f.read())
                except OSError:
                    data.append(None)
            self._same_files[path] = data[0] is not None and data[0] == data[1]
        return self._same_files[path]

    def same_static(self, deck, before, after):
        """True only when nothing that could change the slide's pixels differs.

        Same position, the same raw slide markup including its <section> tags,
        the same deck HTML outside the slides, and byte-identical files for
        every file the slide references and every file either deck has loaded.
        Otherwise, or with live content, the pixels are compared.
        """
        return _same_static(self, self._loaded, deck, before, after)

    def slide_ids(self, side, deck):
        return self.page(side, deck).evaluate("() => Reveal.getSlides().map(s => s.id)")

    def texts(self, side, deck):
        return self.page(side, deck).evaluate(LIST_JS)

    def interactions(self, side, deck):
        return self.page(side, deck).evaluate(INTERACTIONS_JS)

    def shoot(self, side, deck, index, path=None, mark=None, number=False, words=None):
        """Screenshot slide ``index``; ``mark`` is (js, arg) applied on a fresh page.

        ``number`` shows the deck's own slide number, for display rather than comparison.
        A shot written to ``path`` is a display shot at ``DISPLAY_SCALE``; ``words``,
        a list, receives its visible words' boxes.
        """
        page = self._open(side, deck) if mark else self.page(side, deck)
        try:
            page.evaluate(GOTO_JS, index)
            page.evaluate(READY_JS)
            # Embedded documents have their own fonts, media and animation clocks.
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    if frame.frame_element().is_visible():
                        frame.add_style_tag(content=CAPTURE_CSS)
                        frame.evaluate(READY_JS)
                except Exception:
                    # Blocked external embeds and detached frames stay missing in
                    # the picture; they must not discard the rest of the deck.
                    continue
            if number:
                page.evaluate(NUMBER_JS, True)
            if mark:
                page.evaluate(*mark)
            if words is not None:
                words.extend(page.evaluate(WORDS_JS))
            data = page.screenshot(
                type="png",
                animations="disabled",
                scale="device" if path else "css",
            )
        finally:
            if number and not mark:
                page.evaluate(NUMBER_JS, False)
            if mark:
                page.close()
        if path:
            with open(path, "wb") as f:
                f.write(data)
        return data


# Live slides: the rendered deck itself, with changed words marked in its HTML.
class StaticFiles:
    """same_static() without a browser: the deck's files come from its HTML.

    Files the deck loads are read from the HTML outside the slides, following
    ``url()`` and ``@import`` in local stylesheets; a remote file there is the
    same URL on both sides, since that HTML must match.
    """

    def __init__(self, old_root, new_root):
        self._roots = {"old": old_root, "new": new_root}
        self._same_files = {}
        self._loaded = {}

    def _same_file(self, path):
        return Renderer._same_file(self, path)

    def loaded(self, deck, frame):
        # The frame is the deck HTML outside the slides, as one or more pieces.
        if not isinstance(frame, str):
            head, tail, inner = frame
            frame = head + tail + "".join(inner)
        key = (deck, frame)
        if key not in self._loaded:
            seen, todo = set(), [("/" + posixpath.dirname(deck), frame)]
            while todo:
                base, source = todo.pop()
                for link in ResourceRefs(source).refs:
                    link = html.unescape(link.strip())
                    parts = urlsplit(link)
                    if not link or link.startswith("#") or parts.scheme or parts.netloc:
                        continue
                    path = posixpath.normpath(posixpath.join(base, unquote(parts.path)))
                    if path in seen:
                        continue
                    seen.add(path)
                    if path.endswith(".css"):
                        target = os.path.join(self._roots["new"], path.lstrip("/"))
                        try:
                            with open(target, encoding="utf-8", errors="replace") as f:
                                todo.append((posixpath.dirname(path), f.read()))
                        except OSError:
                            pass
            self._loaded[key] = seen
        return self._loaded[key]

    def same_static(self, deck, before, after):
        if after.get("frame") is None:
            return False
        loaded = {deck: self.loaded(deck, after["frame"])}
        return _same_static(self, loaded, deck, before, after)


_TEXT_RE = re.compile(
    r"(<(script|style)\b.*?</\2\s*>|<!--.*?-->|<[^>]*>)|([^<]+)", re.S | re.I
)
_WORD_RE = re.compile(r"\S+")


def slide_words(raw):
    """The words of a slide's raw markup, in order, outside tags, scripts and styles."""
    return [
        w.group()
        for m in _TEXT_RE.finditer(raw)
        if m.group(3)
        for w in _WORD_RE.finditer(m.group(3))
    ]


def word_changes(old_raw, new_raw):
    """(deleted indices into the old words, inserted indices into the new words)."""
    import difflib

    old, new = slide_words(old_raw), slide_words(new_raw)
    deleted, inserted = set(), set()
    for op, a0, a1, b0, b1 in difflib.SequenceMatcher(
        None, old, new, autojunk=False
    ).get_opcodes():
        if op != "equal":
            deleted.update(range(a0, a1))
            inserted.update(range(b0, b1))
    return deleted, inserted


def mark_words(raw, indices, tag):
    """Wrap the words at ``indices`` (as counted by slide_words) in ``<tag>``."""
    out, k = [], 0
    for m in _TEXT_RE.finditer(raw):
        if not m.group(3):
            out.append(m.group())
            continue
        text, pos = m.group(3), 0
        for w in _WORD_RE.finditer(text):
            out.append(text[pos : w.start()])
            word = w.group()
            out.append(
                f'<{tag} class="dr-live">{word}</{tag}>' if k in indices else word
            )
            pos, k = w.end(), k + 1
        out.append(text[pos:])
    return "".join(out)


LIVE_MARK_CSS = (
    "<style>ins.dr-live,del.dr-live{text-decoration:none;border-radius:2px}"
    "ins.dr-live{background:rgba(47,191,113,.35)}"
    "del.dr-live{background:rgba(253,70,69,.35);text-decoration:line-through}</style>"
)


def marked_deck(doc, slides, marks, tag):
    """``doc`` with each slide index in ``marks`` re-marked; ``slides`` from SlideParser.

    Marks change only inline backgrounds, so slides keep their layout."""
    for index in sorted(marks, key=lambda i: slides[i]["span"][0], reverse=True):
        start, end = slides[index]["span"]
        doc = doc[:start] + mark_words(doc[start:end], marks[index], tag) + doc[end:]
    head = re.search(r"</head\s*>", doc, re.I)
    if head:
        doc = doc[: head.start()] + LIVE_MARK_CSS + doc[head.start() :]
    return doc


def classify(old, new, pairs, same_image=None, same_text=None, same_interactions=None):
    """Rows in deck order as (kind, new_index, old_index), and removed old indices.

    ``same_text(old_index, new_index)`` compares the text as shown, so a slide
    whose markup is equal but whose section line changed counts as changed.
    ``same_image`` then decides text-equal slides; without it they count as
    unchanged. ``same_interactions`` also retains edits to links and controls
    whose visible words and pixels stay the same.
    """
    rows = []
    for index in range(len(new)):
        before = pairs.get(index)
        if before is None:
            rows.append(("new", index, None))
        elif (
            old[before]["body"] != new[index]["body"]
            if same_text is None
            else not same_text(before, index)
        ) or (same_interactions is not None and not same_interactions(before, index)):
            # Rendered text includes chrome outside the markup, such as the section line.
            rows.append(("changed", index, before))
        elif same_image is not None and not same_image(before, index):
            rows.append(("look", index, before))
        else:
            rows.append(("unchanged", index, before))
    removed = [index for index in range(len(old)) if index not in pairs.values()]
    return rows, removed


def live_rows(old, new, pairs, same_static):
    """classify() without a browser: words from raw markup; static bytes decide look.

    ``same_static(old_slide, new_slide)`` is True only when nothing that could
    change the slide's pixels differs; a text-equal slide failing it is "look".
    """
    old_words = [slide_words(slide.get("raw", "")) for slide in old]
    new_words = [slide_words(slide.get("raw", "")) for slide in new]
    return classify(
        old,
        new,
        pairs,
        lambda o, n: same_static(old[o], new[n]),
        lambda o, n: old_words[o] == new_words[n],
    )


def live_review(deck, old_doc, new_doc, old, new, pairs, files, old_url, new_url):
    """Browser-free live cards and marked deck documents; no persistent state."""
    rows, removed = live_rows(
        old, new, pairs, lambda a, b: files.same_static(deck, a, b)
    )
    if not removed and all(kind == "unchanged" for kind, _, _ in rows):
        return None, old_doc, new_doc
    deleted, inserted = {}, {}
    for kind, n, o in rows:
        if o is not None:
            deleted[o], inserted[n] = word_changes(old[o]["raw"], new[n]["raw"])
        else:
            inserted[n] = set(range(len(slide_words(new[n]["raw"]))))
    for o in removed:
        deleted[o] = set(range(len(slide_words(old[o]["raw"]))))
    cards, folded = [], []

    def frame(url, slide, side):
        anchor = quote(slide.get("anchor") or slide.get("id") or "", safe="/")
        src = html.escape(url + "?embedded=true#/" + anchor, quote=True)
        return (
            f"<figure><figcaption>{side}</figcaption>"
            f'<iframe loading="lazy" title="{side} slide" src="{src}"></iframe>'
            '<button type="button" data-step="prev">Previous build</button> '
            '<button type="button" data-step="next">Next build</button></figure>'
        )

    def card(kind, n, o):
        number = n + 1 if n is not None else o + 1
        slide = new[n] if n is not None else old[o]
        label = "changed in look" if kind == "look" else kind
        body = frame(old_url, old[o], "Before") if o is not None else ""
        body += frame(new_url, new[n], "After") if n is not None else ""
        return (
            f'<article class="dr-slide dr-{kind}"><h3>Slide {number}: '
            f"{html.escape(slide_title(slide))} — {label}</h3>"
            f'<div class="dr-pair">{body}</div></article>'
        )

    def flush():
        if folded:
            # Inert templates ensure folded slides load no decks until opened.
            cards.append(
                f'<details class="dr-unchanged"><summary>{len(folded)} unchanged slides</summary>'
                "<template>" + "".join(folded) + "</template></details>"
            )
            folded.clear()

    for kind, n, o in rows:
        if kind == "unchanged":
            folded.append(card(kind, n, o))
        else:
            flush()
            cards.append(card(kind, n, o))
    flush()
    cards.extend(card("removed", None, o) for o in removed)
    count = sum(kind != "unchanged" for kind, _, _ in rows)
    body = (
        f'<div class="deck-live deck-review"><p>{count} changed or new; {len(removed)} removed; '
        f"{len(new)} slides</p>" + "".join(cards) + "</div>"
    )
    return (
        body,
        marked_deck(old_doc, old, deleted, "del"),
        marked_deck(new_doc, new, inserted, "ins"),
    )


LIVE_STYLE = """<style>
.deck-live .dr-pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.deck-live figure{margin:0;min-width:0}
.deck-live iframe{width:100%;aspect-ratio:16/9;border:1px solid #888}
.deck-live h3{font-size:1rem}.deck-live summary{cursor:pointer}
</style>"""
LIVE_SCRIPT = """<script>
document.querySelectorAll('.deck-live').forEach(root => {
 root.addEventListener('click', e => {
  const button = e.target.closest('[data-step]'); if (!button) return;
  const frame = button.closest('figure').querySelector('iframe');
  const reveal = frame.contentWindow.Reveal;
  if (reveal) reveal[button.dataset.step + "Fragment"]();
 });
 root.querySelectorAll('details').forEach(details => details.addEventListener('toggle', () => {
  const template = details.querySelector('template');
  if (details.open && template) template.replaceWith(template.content.cloneNode(true));
 }));
});
</script>"""


def context(rows):
    """Keep every slide; the view folds complete unchanged runs behind a count."""
    return list(range(len(rows)))


def slide_title(slide):
    match = re.search(r"<h[12][^>]*>(.*?)</h[12]>", slide["body"], re.S)
    text = re.sub(r"<[^>]+>", "", match.group(1)) if match else ""
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def review(deck, link, img_dir, img_url, old, new, pairs, renderer):
    """Render a deck's changes; return the view's HTML, or None if nothing changed.

    ``old`` is empty for a new deck; ``new`` is never empty here.
    """
    # Refuse a mismatched parser/browser mapping rather than annotate the wrong slide.
    for side, slides in (("old", old), ("new", new)):
        if slides and renderer.slide_ids(side, deck) != [
            slide["id"] for slide in slides
        ]:
            raise ValueError(f"{side} slide order differs between HTML and Reveal")
    os.makedirs(img_dir, exist_ok=True)
    captures = {}

    def shot(side, index):
        if (side, index) not in captures:
            captures[side, index] = renderer.shoot(side, deck, index)
        return captures[side, index]

    old_text = renderer.texts("old", deck) if old else []
    new_text = renderer.texts("new", deck)
    old_interactions = renderer.interactions("old", deck) if old else []
    new_interactions = renderer.interactions("new", deck)
    same_static = getattr(renderer, "same_static", None)

    def same_image(o, n):
        if same_static is not None and same_static(deck, old[o], new[n]):
            return True
        return shot("old", o) == shot("new", n)

    rows, removed = classify(
        old,
        new,
        pairs,
        same_image if old else None,
        lambda o, n: old_text[o] == new_text[n],
        lambda o, n: old_interactions[o] == new_interactions[n],
    )
    shown = context(rows)
    if not removed and all(rows[k][0] == "unchanged" for k in shown):
        return None
    text = {}

    def display(side, index, name, mark=None, number=True):
        words = []
        renderer.shoot(
            side,
            deck,
            index,
            os.path.join(img_dir, name + ".png"),
            mark,
            number=number,
            words=words,
        )
        url = f"{img_url}/{name}.png"
        text[url] = words
        return url

    items = []
    for k in shown:
        kind, n, o = rows[k]
        name = f"s{n + 1}"
        clean = display("new", n, name)
        item = {
            "n": n + 1,
            "kind": kind,
            "title": slide_title(new[n]),
            "clean": clean,
            "link": link + "#/" + new[n]["anchor"],
        }
        if o is not None and old_interactions[o] != new_interactions[n]:
            item["interactions"] = {
                "before": old_interactions[o],
                "after": new_interactions[n],
            }
        mark = None
        if kind == "new":
            mark = (FRAME_JS, [MARK_CSS, "#2fbf71", "New slide"])
        elif kind == "changed":
            mark = (MARK_WORDS_JS, [MARK_CSS, old_text[o].split()])
        if mark:
            item["marked"] = display("new", n, name + "-m", mark)
        if kind in {"changed", "look"}:
            item["before"] = display("old", o, name + "-b")
        items.append(item)
    gone = []
    for o in removed:
        name = f"r{o + 1}"
        mark = (FRAME_JS, [MARK_CSS, "#fd4645", "Removed"])
        url = display("old", o, name, mark, number=False)
        gone.append({"n": o + 1, "title": slide_title(old[o]), "img": url})
    return view(items, gone, len(new), text)


def view(items, removed, total, text=None):
    """``text`` maps an image URL to its words' boxes, laid over it as selectable text."""
    data = json.dumps(
        {"items": items, "removed": removed, "total": total, "text": text or {}}
    )
    return VIEW.replace("__DATA__", data.replace("<", "\\u003c"))


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
.deck-review .dr-shot{position:relative;container-type:inline-size}
.deck-review .dr-text{position:absolute;inset:1px;overflow:hidden}
.deck-review .dr-text span{position:absolute;color:transparent;white-space:pre;line-height:1;transform-origin:0 0;cursor:text}
.deck-review .dr-text span::selection{background:rgba(0,120,255,.3);color:transparent}
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
  root.querySelector('.dr-count').textContent = parts.join(', ') + ' — new deck has ' + D.total + ' slides';
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const imageLabel = (slide, mode) => 'Slide ' + slide.n + (slide.title ? ': ' + slide.title : '') + ' (' + mode + ')';
  const img = (src, slide, mode) => { const i = el('img'); i.src = src;
    i.alt = imageLabel(slide, mode);
    i.loading = 'lazy'; return i; };
  // Transparent words over the image, each stretched to its box on the slide, so
  // text selects and copies like the slide's own (one line break per line).
  const font = getComputedStyle(root).fontFamily || 'sans-serif';
  const ctx = document.createElement('canvas').getContext('2d'); ctx.font = '100px ' + font;
  const paint = (w, src, label) => {
    const image = w.querySelector('img'); image.src = src;
    const layer = w.querySelector('.dr-text'); layer.replaceChildren();
    const words = (D.text || {})[src] || [];
    words.forEach(([t, x, y, ww, h], k) => {
      const next = words[k + 1];
      // Raised/lowered words can share a line despite having different tops.
      const sameLine = next && Math.min(y + h, next[2] + next[4]) > Math.max(y, next[2]);
      const s = el('span', null, t + (sameLine ? ' ' : '\\n'));
      const size = h * 56.25 * 0.85;
      const natural = ctx.measureText(t).width || 1;
      Object.assign(s.style, { left: x * 100 + '%', top: (y + h * 0.075) * 100 + '%', fontSize: size + 'cqw',
        transform: 'scaleX(' + (ww * 100 * 100 / (natural * size)) + ')' });
      layer.append(s);
    });
    // Expose the slide's text once, as a continuous image description rather
    // than a second reading of every positioned word in the selection overlay.
    const text = layer.textContent.trim();
    image.alt = label + (text ? '\\n' + text : '');
  };
  const shot = (src, slide, mode) => {
    const w = el('div', 'dr-shot'); const i = img(src, slide, mode); i.draggable = false;
    const layer = el('div', 'dr-text'); layer.setAttribute('aria-hidden', 'true');
    w.append(i, layer); paint(w, src, imageLabel(slide, mode)); return w;
  };
  const label = { new: 'new', changed: 'changed', look: 'changed look', removed: 'removed' };
  const card = (i) => {
    const s = el('section', 'dr-slide dr-' + i.kind);
    // The slide image shows its title and number; the heading is just the status, linked to the slide.
    const word = label[i.kind] || 'unchanged';
    const h = el('h3'); const a = el('a', 'tag ' + (i.kind === 'look' ? 'changed' : i.kind), word + ' \u2197'); a.href = i.link;
    a.setAttribute('aria-label', 'Slide ' + i.n + (i.title ? ': ' + i.title : '') + ', ' + word); h.append(a);
    const one = shot(i.marked || i.clean, i, i.marked ? 'marked' : 'clean');
    one.dataset.clean = i.clean; one.dataset.marked = i.marked || i.clean;
    one.dataset.cleanAlt = imageLabel(i, 'clean'); one.dataset.markedAlt = imageLabel(i, i.marked ? 'marked' : 'clean');
    s.append(h, one);
    if (i.interactions) {
      const note = el('div', 'dr-interactions');
      note.append(el('strong', null, 'Links or controls changed'));
      for (const [key, label] of [['before', 'Before'], ['after', 'After']]) {
        const p = el('p'); p.append(el('b', null, label + ': '));
        p.append(el('code', null, i.interactions[key].map(x =>
          x.element + (x.label ? ' “' + x.label + '”' : '') + ' ' + JSON.stringify(x.attributes)
        ).join('; ') || '(none)')); note.append(p);
      }
      s.append(note);
    }
    if (i.before) {
      const p = el('div', 'dr-pair'); p.hidden = true;
      [['Before', i.before], ['After', i.clean]].forEach(([c, src]) => { const f = el('figure'); f.append(el('figcaption', null, c), shot(src, i, c.toLowerCase())); p.append(f); });
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
    const s = el('section', 'dr-slide dr-removed'); const h = el('h3');
    const t = el('span', 'tag removed', 'removed'); t.setAttribute('aria-label', 'Slide ' + r.n + ' of the old deck' + (r.title ? ': ' + r.title : '') + ', removed');
    h.append(t); s.append(h, shot(r.img, r, 'removed')); list.append(s);
  }
  const set = (v) => {
    root.querySelectorAll('.dr-seg button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === v)));
    root.querySelectorAll('.dr-shot[data-clean]').forEach((w) => {
      paint(w, v === 'clean' ? w.dataset.clean : w.dataset.marked,
        v === 'clean' ? w.dataset.cleanAlt : w.dataset.markedAlt);
      const p = w.parentElement.querySelector('.dr-pair');
      if (p) { p.hidden = v !== 'before'; w.hidden = v === 'before'; }
    });
  };
  root.querySelectorAll('.dr-seg button').forEach((b) => { b.onclick = () => set(b.dataset.v); });
});
</script>"""
