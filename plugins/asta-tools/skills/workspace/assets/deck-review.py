"""Browser-free live slide review: static input comparison and marked deck frames.

Each slide in the report is an iframe, and a self-contained Reveal deck is one
big document: for a real 58-slide talk, 6.2 MB, of which 3.7 MB is the same
fonts, styles and scripts in every frame. Loading that whole deck to show one
slide left a deck that is new, or changes many slides, blank for minutes.

So a frame is not the deck but a *frame document*: the deck with every other
slide emptied to a placeholder section (positions, slide numbers and ``#/``
anchors stay as in the deck) and with its large inline pieces (stylesheets,
scripts, fonts, images) moved to files shared by all frames, which the browser
fetches and parses once. A frame then costs the one slide plus a few KB, so many
frames load within seconds. The frame is still a live Reveal deck, so the slide
shows in place, sharp, with selectable text. The full marked decks are still
published for opening on their own.

Slides run sandboxed, with no access to the page that shows them: each frame is
``sandbox="allow-scripts"`` and nothing more, so a deck's own scripts run in an
opaque origin and cannot reach the report's DOM, storage or origin. The viewer
therefore never reaches into a frame; it only posts it Reveal's ``layout`` message.
"""

import hashlib
import html
import importlib.util
import os
import posixpath
import re
from base64 import b64decode
from html.parser import HTMLParser
from urllib.parse import quote, unquote, unquote_to_bytes, urlsplit


def _load_diff_engine():
    """diff-engine.py beside this file: the pages' diff, whose rules the slides share."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diff-engine.py")
    spec = importlib.util.spec_from_file_location("diff_engine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DIFF_ENGINE = _load_diff_engine()

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


class SlideText(HTMLParser):
    """Source spans of visible prose, preserving nested graphics/code verbatim."""

    PROTECTED = {"script", "style", "svg", "math", "textarea", "pre", "code"}
    VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self, raw):
        super().__init__(convert_charrefs=False)
        self.raw, self.stack, self.spans, self.notes = raw, [], [], []
        self.lines = [0] + [match.end() for match in re.finditer("\n", raw)]
        self.feed(raw)
        self.close()
        for _, _, note in self.stack:
            if note is not None:
                self.notes.append((note, len(raw)))

    def _offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        note = tag == "aside" and "notes" in (dict(attrs).get("class") or "").split()
        protected = (
            (bool(self.stack) and self.stack[-1][1]) or tag in self.PROTECTED or note
        )
        if tag not in self.VOID:
            self.stack.append((tag, protected, self._offset() if note else None))

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                end = self.raw.find(">", self._offset()) + 1
                for _, _, note in self.stack[index:]:
                    if note is not None:
                        self.notes.append((note, end))
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.stack and self.stack[-1][1]:
            return
        start = self._offset()
        end = start + len(data)
        if self.spans and self.spans[-1][1] == start:
            self.spans[-1] = (self.spans[-1][0], end)
        else:
            self.spans.append((start, end))

    def handle_entityref(self, name):
        value = "&" + name
        if self.raw.startswith(value + ";", self._offset()):
            value += ";"
        self.handle_data(value)

    def handle_charref(self, name):
        self.handle_entityref("#" + name)


def without_notes(raw):
    if "notes" not in raw:
        return raw
    # Merge overlapping nested-note ranges before removing them.
    out, end = [], 0
    for start, stop in sorted(SlideText(raw).notes):
        if start >= end:
            out.append(raw[end:start])
        end = max(end, stop)
    return "".join(out) + raw[end:]


def _same_static(files, loaded, deck, before, after, positional=True):
    # Pixels include the slide number; a live frame's own number isn't a change.
    old_raw = without_notes(before.get("raw") or "")
    new_raw = without_notes(after.get("raw") or "")
    if (
        before.get("raw") is None
        or old_raw != new_raw
        or (positional and before.get("position") != after.get("position"))
        or before.get("frame") != after.get("frame")
        or LIVE_RE.search(new_raw)
    ):
        return False
    # The deck documents themselves are compared as raw slides and frame.
    paths = set(loaded.get(deck, set())) - {"/" + deck}
    refs = _local_paths(new_raw, "/" + posixpath.dirname(deck))
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


MATH_RE = re.compile(
    r"(\\\(.*?\\\)|\\\[.*?\\\]|\$\$.*?\$\$|(?<!\\)\$(?!\s).*?(?<!\\)\$)",
    re.S,
)
_WORD_RE = re.compile(r"\S+")


def text_parts(raw):
    """Raw, lossless pieces with only ordinary visible prose eligible for marks.

    TeX delimiters and markup interpreted by another renderer stay intact.
    They still participate in the static comparison as appearance changes.
    """
    end = 0
    for start, stop in SlideText(raw).spans:
        yield raw[end:start], False
        for i, part in enumerate(MATH_RE.split(raw[start:stop])):
            if part:
                yield part, i % 2 == 0
        end = stop
    yield raw[end:], False


def slide_words(raw):
    """Words of visible prose only; protected rendering markup is left intact."""
    return [
        w.group()
        for text, visible in text_parts(raw)
        if visible
        for w in _WORD_RE.finditer(text)
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

    close = f"</{tag}>"
    for text, visible in text_parts(raw):
        if not visible:
            out.append(text)
            continue
        pos, run = 0, False
        for w in _WORD_RE.finditer(text):
            gap, word = text[pos : w.start()], w.group()
            if (
                run
                and k in indices
                and not struck.get(k)
                # Only spaces between two changed words: one mark, by the same
                # rule as on the pages.
                and DIFF_ENGINE.gap_joins_marks([("space", gap)])
            ):
                out.append(gap + word)
            else:
                if run:
                    out.append(close)
                out.append(gap)
                strike(k)
                if k in indices:
                    out.append(f'<{tag} class="dr-live">{word}')
                else:
                    out.append(word)
                run = k in indices
            pos, k = w.end(), k + 1
        if run:
            out.append(close)
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
    # No in-frame navigation: the page's list of slides is the one way through.
    # Hidden in CSS because a deck's own scripts can re-enable `controls`.
    "<style>.reveal .controls,.reveal .progress,.slide-menu-button,"
    ".reveal .slide-menu,.reveal .slide-chalkboard-buttons{display:none!important}</style>"
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


FRAME_ASSETS = "frame-assets"
# Pieces under these sizes stay inline: a request costs more than they weigh.
BIG_BLOCK = 8192
BIG_DATA = 2048

_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_HREF_RE = re.compile(
    r"""\bhref\s*=\s*(["'])(data:text/css[^"']*?),(.*?)\1""", re.I | re.S
)
_STYLE_RE = re.compile(r"<style\b([^>]*)>(.*?)</style\s*>", re.I | re.S)
_SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.I | re.S)
_PLAIN_RE = re.compile(
    r"""\s*(?:type\s*=\s*["']?text/(?:css|javascript)["']?\s*)?""", re.I
)
_DATA_RE = re.compile(
    r"data:(image/(?:png|jpeg|gif|webp|avif|svg\+xml)|font/(?:woff2?|ttf|otf));base64,"
    rf"([A-Za-z0-9+/=]{{{BIG_DATA},}})"
)
_DECK_WIDE_RE = re.compile(
    r"<style\b.*?</style\s*>|<script\b.*?</script\s*>|<link\b[^>]*>", re.S | re.I
)
_EXTENSION = {
    "image/svg+xml": ".svg",
    "image/jpeg": ".jpg",
    "font/woff": ".woff",
    "font/woff2": ".woff2",
}


def frame_path(path, kind, index):
    """Where the frame document for slide ``index`` of a deck is published."""
    root, ext = posixpath.splitext(path)
    return f"{root}.frame-{kind}-{index + 1}{ext}"


class FrameAssets:
    """Large inline pieces of decks, moved to files every frame document shares.

    ``prefix`` is the relative URL from the frame documents to the files, which
    are kept in ``files`` by content-derived name. Only pieces that load the same
    from a file are moved: stylesheets without relative ``url()``/``@import``,
    plain scripts that do not read their own address, and base64 images/fonts.
    """

    def __init__(self, prefix):
        self.prefix = prefix
        self.files = {}

    def _store(self, data, ext):
        name = hashlib.sha256(data).hexdigest()[:24] + ext
        self.files[name] = data
        return self.prefix + name

    def _link(self, tag):
        match = _HREF_RE.search(tag)
        if not match or len(match.group(3)) < BIG_BLOCK:
            return tag
        payload = html.unescape(match.group(3))
        try:
            if ";base64" in match.group(2).lower():
                data = b64decode(payload, validate=True)
            else:
                data = unquote_to_bytes(payload)
        except ValueError:
            return tag
        url = self._store(data, ".css")
        return tag[: match.start()] + f'href="{url}"' + tag[match.end() :]

    def _style(self, match):
        if (
            _PLAIN_RE.fullmatch(match.group(1)) is None
            or len(match.group(2)) < BIG_BLOCK
        ):
            return match.group(0)
        # A stylesheet that names other files by relative URL would look in the
        # wrong directory once it moves.
        if any(
            not ref.startswith("data:")
            for ref in ResourceRefs(match.group(2), True).refs
        ):
            return match.group(0)
        url = self._store(match.group(2).encode(), ".css")
        return f'<link rel="stylesheet" href="{url}">'

    def _script(self, match):
        code = match.group(2)
        if (
            _PLAIN_RE.fullmatch(match.group(1)) is None
            or len(code) < BIG_BLOCK
            or "currentScript" in code
        ):
            return match.group(0)
        return f'<script src="{self._store(code.encode(), ".js")}"></script>'

    def _data(self, match):
        mime = match.group(1)
        try:
            data = b64decode(match.group(2), validate=True)
        except ValueError:
            return match.group(0)
        return self._store(data, _EXTENSION.get(mime, "." + mime.split("/")[1]))

    def move(self, text):
        """``text`` with its large pieces replaced by links to shared files."""
        if len(text) < BIG_DATA:
            return text
        text = _LINK_RE.sub(lambda m: self._link(m.group(0)), text)
        text = _STYLE_RE.sub(self._style, text)
        text = _SCRIPT_RE.sub(self._script, text)
        return _DATA_RE.sub(self._data, text)


class FrameDocs:
    """Frame documents of one deck: ``doc`` with one slide kept, the rest emptied.

    ``slides`` are SlideParser's slides of ``doc``. The HTML around the slides is
    prepared once, so a frame costs only its own slide. An emptied slide keeps its
    place (so numbers and anchors hold) and any style, script or link in it,
    since those can restyle the slide that is kept.
    """

    def __init__(self, doc, slides, assets):
        self.doc, self.slides, self.assets = doc, slides, assets
        self.gaps, end = [], 0
        for slide in slides:
            start, stop = slide["span"]
            self.gaps.append(doc[end:start])
            end = stop
        self.gaps.append(doc[end:])
        head = re.search(r"</head\s*>", self.gaps[0], re.I)
        if head:
            self.gaps[0] = (
                self.gaps[0][: head.start()]
                + LIVE_MARK_CSS
                + self.gaps[0][head.start() :]
            )
        self.gaps = [assets.move(gap) for gap in self.gaps]
        self.holders = [self._holder(doc[slice(*slide["span"])]) for slide in slides]

    def _holder(self, text):
        # What the deck and its theme read from every slide stays: whether a slide
        # is hidden or uncounted, and its section (asta-slides.js builds the
        # section headline from every slide's data-asta-section*). Anything that
        # draws or sizes the slide (id, class, background) does not.
        opening = re.match(r"<section\b[^>]*>", text, re.I)
        kept = re.findall(
            r"""\bdata-(?:visibility|asta-[\w-]+)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""",
            opening.group(0) if opening else "",
            re.I,
        )
        return (
            "<section"
            + "".join(" " + attribute for attribute in kept)
            + ">"
            + self.assets.move("".join(_DECK_WIDE_RE.findall(text)))
            + "</section>"
        )

    def text(self, index):
        return self.doc[slice(*self.slides[index]["span"])]

    def render(self, index, text=None):
        """The frame document for slide ``index``, optionally with its markup ``text``."""
        kept = self.assets.move(self.text(index) if text is None else text)
        parts = []
        for i, gap in enumerate(self.gaps[:-1]):
            parts.append(gap)
            parts.append(kept if i == index else self.holders[i])
        parts.append(self.gaps[-1])
        return "".join(parts)


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
    """Browser-free live cards, marked deck documents and the frame documents.

    Returns ``(body, before, after, marked, frames)``: the report HTML; the old
    and new decks and the new deck with changes marked, each for opening whole;
    and ``frames``, ``{(side, path): document}`` with ``side`` "before" or
    "after" (relative to that side's copy of the site) or "shared", for the files
    every frame document links to (``path`` relative to the frame assets).
    """
    rows, removed = live_rows(
        old, new, pairs, lambda a, b: files.same_static(deck, a, b)
    )
    if not removed and all(kind == "unchanged" for kind, _, _ in rows):
        return None, old_doc, new_doc, None, {}
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
    # From a frame document at <root>/<side>/<deck> up to <root>/<FRAME_ASSETS>.
    assets = FrameAssets("../" * (deck.count("/") + 1) + FRAME_ASSETS + "/")
    docs = {
        "before": FrameDocs(old_doc, old, assets),
        "after": FrameDocs(new_doc, new, assets),
    }
    frames = {}

    def frame_src(kind, index):
        """Publish the frame document of a slide in a view; its URL."""
        side = "before" if kind == "before" else "after"
        name = frame_path(deck, kind, index)
        if (side, name) not in frames:
            if kind == "marked":
                text = mark_words(
                    docs[side].text(index), inserted[index], "ins", struck.get(index)
                )
                frames[side, name] = docs[side].render(index, text)
            else:
                frames[side, name] = docs[side].render(index)
        return frame_path(old_url if side == "before" else new_url, kind, index)

    def frame(src, slide, side, view, role=""):
        """One slide's frame. `role` is "old" or "new" for the frames of Before /
        after (and a removed slide), which the page draws in a thin red or
        green frame under a label of the same colour, as it draws a figure."""
        anchor = quote(slide.get("anchor") or slide.get("id") or "", safe="/")
        # Reveal's narrow-screen scroll view ignores slide hashes; query config
        # outranks the deck's. Navigation is off so a frame stays on its slide.
        src = html.escape(f"{src}?{FRAME_CONFIG}#/{anchor}", quote=True)
        slide_id = html.escape(slide.get("id") or slide.get("anchor") or "", quote=True)
        role_class = f' class="dr-{role}"' if role else ""
        return (
            f'<figure data-view="{view}"{role_class}>'
            f"<figcaption>{side}</figcaption>"
            f'<iframe loading="lazy" sandbox="allow-scripts" title="{side} slide" '
            f'data-dr-slide-id="{slide_id}" data-src="{src}"></iframe></figure>'
        )

    def card(kind, n, o):
        number = n + 1 if n is not None else o + 1
        slide = new[n] if n is not None else old[o]
        label = "changed in look" if kind == "look" else kind
        if n is None:
            body = frame(
                frame_src("before", o),
                old[o],
                "Removed",
                "marked clean before",
                "old",
            )
        else:
            clean = frame_src("clean", n)
            # A slide with no word changed has no marks, so Changes marked is its
            # clean frame. Before is always the old deck's own slide: its place,
            # number, anchor and notes can differ from the new deck's.
            marks = inserted.get(n) or struck.get(n)
            marked = frame_src("marked", n) if marks else clean
            before = frame_src("before", o) if o is not None else clean
            body = frame(marked, new[n], "Changes marked", "marked")
            body += frame(clean, new[n], "Clean", "clean")
            if o is not None:
                body += frame(before, old[o], "Before", "before", "old")
            body += frame(clean, new[n], "After", "before", "new")
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
            # The strip reads as the page's own fold strips do.
            cards.append(
                f'<details class="dr-unchanged wc-expander"><summary>'
                f'<span class="wc-expander-icon" aria-hidden="true">↕</span> '
                f"⋯ {len(folded)} unchanged slide{'s' if len(folded) > 1 else ''}"
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
    for name, data in assets.files.items():
        frames["shared", name] = data
    return (
        body,
        marked_deck(old_doc, old, {}, "del"),
        marked_deck(new_doc, new, {}, "ins"),
        marked_deck(new_doc, new, inserted, "ins", struck),
        frames,
    )


# minScale: Reveal stops shrinking a slide at 0.2 of its size by default, which
# clips a 1600px deck in any frame under 320px; a frame's slide always fits it.
FRAME_CONFIG = (
    "view=slide&scrollActivationWidth=0&fragments=false&keyboard=false&touch=false"
    "&controls=false&mouseWheel=false&overview=false&help=false&minScale=0.05"
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
/* Before and After side by side while each gets 320px, else one above the other;
   the deck's own width decides, whatever page holds it. */
.deck-live{container:deck-live / inline-size}
@container deck-live (max-width: 649px){.deck-live[data-view=before] .dr-pair{grid-template-columns:minmax(0,1fr)}}
.deck-live figure{margin:0;min-width:0}.deck-live figcaption{font-size:.8rem;opacity:.75}
.deck-live[data-view=marked] figure:not([data-view~=marked]),
.deck-live[data-view=clean] figure:not([data-view~=clean]),
.deck-live[data-view=before] figure:not([data-view~=before]){display:none}
.deck-live iframe{width:100%;aspect-ratio:16/9;border:1px solid #888;display:block}
.deck-live figure.dr-old iframe,.deck-live figure.dr-new iframe{border-radius:6px}
.deck-live figure.dr-old iframe{border-color:var(--wc-del-line,#c41d2c)}
.deck-live figure.dr-new iframe{border-color:var(--wc-ins-line,#2a7a12)}
.deck-live figure.dr-old figcaption,.deck-live figure.dr-new figcaption{font:600 .72rem/1.3 system-ui,sans-serif;letter-spacing:.02em;margin-bottom:.35rem;opacity:1}
.deck-live figure.dr-old figcaption{color:var(--wc-del-line,#c41d2c)}
.deck-live figure.dr-new figcaption{color:var(--wc-ins-line,#2a7a12)}
.deck-live h3{font-size:1rem}
.wc-expander{margin:8px 0}
</style>"""


LIVE_SCRIPT = """<script>
document.querySelectorAll('.deck-live').forEach(root => {
 // Load only shown frames, near the viewport and a few at a time, so that an
 // opened fold does not start dozens at once. A frame is one slide's small
 // document, so a few at a time keep the slides in view ahead of the scroll.
 const shown = f => f.closest('figure').offsetParent !== null;
 const queue = []; let active = 0;
 const start = f => {
  active++; let done = false;
  const finish = () => { if (!done) { done = true; active--; pump(); } };
  f.addEventListener('load', finish, {once: true}); setTimeout(finish, 8000);
  f.src = f.dataset.src; f.removeAttribute('data-src');
 };
 const near = 'IntersectionObserver' in window && new IntersectionObserver(entries => entries.forEach(e => {
  if (e.isIntersecting && e.target.dataset.src) { near.unobserve(e.target); queue.push(e.target); }
 }) || pump(), {rootMargin: '300px 0px'});
 const pump = () => {
  queue.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  while (active < 4 && queue.length) {
   const f = queue.shift();
   if (!f.dataset.src) continue;
   if (shown(f)) start(f); else near.observe(f);
  }
 };
 const load = () => root.querySelectorAll('iframe[data-src]').forEach(f => {
  if (!near) { if (shown(f)) { f.src = f.dataset.src; f.removeAttribute('data-src'); } return; }
  near.observe(f);
 });
 root.querySelectorAll('.dr-seg button').forEach(b => b.addEventListener('click', () => {
  root.dataset.view = b.dataset.v;
  root.querySelectorAll('.dr-seg button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  load();
  // A frame that finished loading while hidden laid out at no size: ask its
  // Reveal to fit it now. Frames are sandboxed, so only a message reaches them.
  root.querySelectorAll('iframe[src]').forEach(f => {
   if (shown(f) && f.contentWindow) f.contentWindow.postMessage('{"method":"layout"}', '*');
  });
 }));
 root.querySelectorAll('details').forEach(details => details.addEventListener('toggle', () => {
  const template = details.querySelector('template');
  if (details.open && template) template.replaceWith(template.content.cloneNode(true));
  load();
 }));
 load();
});
</script>"""


def slide_title(slide):
    match = re.search(r"<h[12][^>]*>(.*?)</h[12]>", slide["body"], re.S)
    text = re.sub(r"<[^>]+>", "", match.group(1)) if match else ""
    return html.unescape(re.sub(r"\s+", " ", text)).strip()
