"""Browser-free live slide review: static input comparison and marked deck frames."""

import html
import os
import posixpath
import re
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urlsplit

LIVE_RE = re.compile(
    r"<(?:script|iframe|canvas|video|audio|object|embed)\b|data-background-(?:iframe|video)",
    re.I,
)


class ResourceRefs(HTMLParser):
    """Loaded resources, excluding outbound links and entire inline data URLs."""

    def __init__(self, source, css=False):
        super().__init__(convert_charrefs=True)
        self.refs = []
        self._in_style = False
        if css:
            self._css(source)
        else:
            self.feed(source)

    def _css(self, text):
        # Only CSS loads url()/@import; the same text in a script or prose loads nothing.
        self.refs.extend(re.findall(r"url\(\s*[\"']?([^\"')]+)", text, re.I))
        self.refs.extend(re.findall(r"@import\s+[\"']([^\"']+)", text, re.I))

    def handle_data(self, data):
        if self._in_style:
            self._css(data)

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_starttag(self, tag, attrs):
        if tag == "style":
            self._in_style = True
        for name, value in attrs:
            if name == "style" and value:
                self._css(value)
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


def _same_static(files, loaded, deck, before, after, positional=True):
    # Pixels include the slide number; a live frame's own number isn't a change.
    if (
        before.get("raw") is None
        or before["raw"] != after.get("raw")
        or (positional and before.get("position") != after.get("position"))
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
            # Absent on both sides loads nothing either way, so it cannot differ.
            self._same_files[path] = data[0] == data[1]
        return self._same_files[path]

    def loaded(self, deck, frame):
        # The frame is the deck HTML outside the slides, as one or more pieces.
        if not isinstance(frame, str):
            head, tail, inner = frame
            frame = head + tail + "".join(inner)
        key = (deck, frame)
        if key not in self._loaded:
            seen, todo = set(), [("/" + posixpath.dirname(deck), frame, False)]
            while todo:
                base, source, css = todo.pop()
                for link in ResourceRefs(source, css).refs:
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
                                todo.append((posixpath.dirname(path), f.read(), True))
                        except OSError:
                            pass
            self._loaded[key] = seen
        return self._loaded[key]

    def same_static(self, deck, before, after):
        if after.get("frame") is None:
            return False
        loaded = {deck: self.loaded(deck, after["frame"])}
        return _same_static(self, loaded, deck, before, after, positional=False)


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


def struck_before(old_raw, new_raw):
    """{new word index: deleted old words shown before it}; key len(new) is the tail."""
    import difflib

    old, new = slide_words(old_raw), slide_words(new_raw)
    struck = {}
    for op, a0, a1, b0, _ in difflib.SequenceMatcher(
        None, old, new, autojunk=False
    ).get_opcodes():
        if op in {"delete", "replace"}:
            struck.setdefault(b0, []).extend(old[a0:a1])
    return struck


def mark_words(raw, indices, tag, struck=None):
    """Wrap the words at ``indices`` (as counted by slide_words) in ``<tag>``.

    ``struck`` puts deleted words, struck through, before the word they preceded."""
    struck = struck or {}
    out, k = [], 0

    def strike(at):
        if struck.get(at):
            out.append('<del class="dr-live">' + " ".join(struck[at]) + "</del> ")

    for m in _TEXT_RE.finditer(raw):
        if not m.group(3):
            out.append(m.group())
            continue
        text, pos = m.group(3), 0
        for w in _WORD_RE.finditer(text):
            out.append(text[pos : w.start()])
            strike(k)
            word = w.group()
            out.append(
                f'<{tag} class="dr-live">{word}</{tag}>' if k in indices else word
            )
            pos, k = w.end(), k + 1
        out.append(text[pos:])
    if struck.get(k):
        # Deleted words after the last kept word go before the slide's last closing tag.
        tail = "".join(out)
        cut = tail.rfind("</")
        out = [tail[:cut]] if cut > 0 else [tail]
        strike(k)
        out.append(tail[cut:] if cut > 0 else "")
    return "".join(out)


LIVE_MARK_CSS = (
    # Every build visible, so a changed word is never hidden behind a fragment.
    "<style>.reveal .slides .fragment{opacity:1!important;visibility:inherit!important;"
    "transform:none!important}</style>"
    "<style>ins.dr-live,del.dr-live{text-decoration:none;border-radius:2px}"
    "ins.dr-live{background:rgba(47,191,113,.35)}"
    "del.dr-live{background:rgba(253,70,69,.35);text-decoration:line-through}</style>"
)


def marked_path(path):
    """Where the after deck with insertions and deletions marked is published."""
    root, ext = posixpath.splitext(path)
    return root + ".marked" + ext


def marked_deck(doc, slides, marks, tag, struck=None):
    """``doc`` with each slide index in ``marks`` re-marked; ``slides`` from SlideParser.

    ``struck`` maps a slide index to struck_before() for deletions on that slide.
    Marks change only inline backgrounds, so slides keep their layout."""
    struck = struck or {}
    for index in sorted(marks, key=lambda i: slides[i]["span"][0], reverse=True):
        start, end = slides[index]["span"]
        doc = (
            doc[:start]
            + mark_words(doc[start:end], marks[index], tag, struck.get(index))
            + doc[end:]
        )
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
        return None, old_doc, new_doc, None
    deleted, inserted, struck = {}, {}, {}
    for kind, n, o in rows:
        if o is not None:
            deleted[o], inserted[n] = word_changes(old[o]["raw"], new[n]["raw"])
            struck[n] = struck_before(old[o]["raw"], new[n]["raw"])
        else:
            inserted[n] = set(range(len(slide_words(new[n]["raw"]))))
    for o in removed:
        deleted[o] = set(range(len(slide_words(old[o]["raw"]))))
    cards, folded = [], []
    marked_url = marked_path(new_url)

    def frame(url, slide, side, view):
        anchor = quote(slide.get("anchor") or slide.get("id") or "", safe="/")
        # Reveal's narrow-screen scroll view ignores slide hashes; query config
        # outranks the deck's. Navigation is off so a frame stays on its slide.
        src = html.escape(f"{url}?{FRAME_CONFIG}#/{anchor}", quote=True)
        slide_id = html.escape(slide.get("id") or slide.get("anchor") or "", quote=True)
        return (
            f'<figure data-view="{view}"><figcaption>{side}</figcaption>'
            f'<iframe loading="lazy" title="{side} slide" data-dr-slide-id="{slide_id}" '
            f'data-src="{src}"></iframe></figure>'
        )

    def card(kind, n, o):
        number = n + 1 if n is not None else o + 1
        slide = new[n] if n is not None else old[o]
        label = "changed in look" if kind == "look" else kind
        if n is None:
            body = frame(old_url, old[o], "Removed", "marked clean before")
        else:
            body = frame(marked_url, new[n], "Changes marked", "marked")
            body += frame(new_url, new[n], "Clean", "clean")
            if o is not None:
                body += frame(old_url, old[o], "Before", "before")
            body += frame(new_url, new[n], "After", "before")
        return (
            f'<article class="dr-slide dr-{kind}"><h3>Slide {number}: '
            f"{html.escape(slide_title(slide))} — {label}</h3>"
            f'<div class="dr-pair">{body}</div></article>'
        )

    def flush():
        if folded:
            first, last = folded[0][0], folded[-1][0]
            span = f"{first}" if first == last else f"{first}–{last}"
            # Inert templates ensure folded slides load no decks until opened.
            cards.append(
                f'<details class="dr-unchanged wc-expander"><summary>'
                f'<span class="wc-expander-icon" aria-hidden="true">↕</span> '
                f"Expand {len(folded)} unchanged slide{'s' if len(folded) > 1 else ''}"
                f" ({span})</summary>"
                "<template>" + "".join(c for _, c in folded) + "</template></details>"
            )
            folded.clear()

    for kind, n, o in rows:
        if kind == "unchanged":
            folded.append((n + 1, card(kind, n, o)))
        else:
            flush()
            cards.append(card(kind, n, o))
    flush()
    cards.extend(card("removed", None, o) for o in removed)
    count = sum(kind != "unchanged" for kind, _, _ in rows)
    body = (
        f'<div class="deck-live deck-review" data-view="marked"><div class="dr-bar">'
        f'<span class="dr-count">{count} changed or new; {len(removed)} removed; '
        f"{len(new)} slides</span>" + VIEW_SWITCH + "</div>" + "".join(cards) + "</div>"
    )
    return (
        body,
        marked_deck(old_doc, old, {}, "del"),
        marked_deck(new_doc, new, {}, "ins"),
        marked_deck(new_doc, new, inserted, "ins", struck),
    )


FRAME_CONFIG = (
    "view=slide&scrollActivationWidth=0&fragments=false&keyboard=false&touch=false"
    "&controls=false&mouseWheel=false&overview=false&help=false"
)


VIEW_SWITCH = (
    '<span class="dr-seg" role="group" aria-label="Slide view">'
    '<button type="button" data-v="marked" aria-pressed="true">Changes marked</button>'
    '<button type="button" data-v="clean" aria-pressed="false">Clean</button>'
    '<button type="button" data-v="before" aria-pressed="false">Before / after</button></span>'
)


LIVE_STYLE = """<style>
.deck-live .dr-bar{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:.5rem 0}
.deck-live .dr-seg{margin-left:auto;display:inline-flex;border:1px solid rgba(127,127,127,.6);border-radius:8px;overflow:hidden}
.deck-live .dr-seg button{font:inherit;background:none;color:inherit;border:0;padding:4px 12px;cursor:pointer;opacity:.7}
.deck-live .dr-seg button[aria-pressed=true]{background:rgba(127,127,127,.3);font-weight:600;opacity:1}
.deck-live .dr-pair{display:grid;grid-template-columns:minmax(0,1fr);gap:10px}
.deck-live[data-view=before] .dr-pair{grid-template-columns:repeat(2,minmax(0,1fr))}
.deck-live figure{margin:0;min-width:0}.deck-live figcaption{font-size:.8rem;opacity:.75}
.deck-live[data-view=marked] figure:not([data-view~=marked]),
.deck-live[data-view=clean] figure:not([data-view~=clean]),
.deck-live[data-view=before] figure:not([data-view~=before]){display:none}
.deck-live iframe{width:100%;aspect-ratio:16/9;border:1px solid #888;display:block}
.deck-live h3{font-size:1rem}
.wc-expander{margin:8px 0}
.wc-expander>summary{list-style:none;cursor:pointer;font-size:.9rem;padding:4px 12px;background:rgba(84,174,255,.12);border:1px solid rgba(84,174,255,.35);border-radius:6px;color:inherit}
.wc-expander>summary::-webkit-details-marker{display:none}
.wc-expander>summary:hover{background:rgba(84,174,255,.25)}
.wc-expander[open]>summary{margin-bottom:8px}
</style>"""


LIVE_SCRIPT = """<script>
document.querySelectorAll('.deck-live').forEach(root => {
 // Load only the frames the current view shows.
 const load = () => root.querySelectorAll('iframe[data-src]').forEach(f => {
  if (f.closest('figure').offsetParent !== null) { f.src = f.dataset.src; f.removeAttribute('data-src'); }
 });
 root.querySelectorAll('.dr-seg button').forEach(b => b.addEventListener('click', () => {
  root.dataset.view = b.dataset.v;
  root.querySelectorAll('.dr-seg button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  load();
 }));
 root.querySelectorAll('details').forEach(details => details.addEventListener('toggle', () => {
  const template = details.querySelector('template');
  if (details.open && template) template.replaceWith(template.content.cloneNode(true));
  load();
 }));
 load();
});
</script>"""


def context(rows):
    """Keep every slide; the view folds complete unchanged runs behind a count."""
    return list(range(len(rows)))


def slide_title(slide):
    match = re.search(r"<h[12][^>]*>(.*?)</h[12]>", slide["body"], re.S)
    text = re.sub(r"<[^>]+>", "", match.group(1)) if match else ""
    return html.unescape(re.sub(r"\s+", " ", text)).strip()
