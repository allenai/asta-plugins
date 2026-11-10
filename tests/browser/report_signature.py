"""Compare content semantics, ignoring layout, paths and generated script data."""

from html.parser import HTMLParser


class ReportSignature(HTMLParser):
    def __init__(self, *, deck=False):
        super().__init__()
        self.pages = set()
        self.deck = deck
        self.marks = []
        self.current = None
        self.sections = []
        self.mark = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section":
            self.sections.append(self.current)
            if "page-diff" in attrs.get("class", "").split() or (
                self.deck and attrs.get("id")
            ):
                self.current = attrs.get("id")
                self.pages.add(self.current)
        if tag in ("ins", "del") and self.current is not None:
            self.mark = tag
            self.text = []

    def handle_endtag(self, tag):
        if tag == self.mark:
            self.marks.append((self.current, tag, " ".join("".join(self.text).split())))
            self.mark = None
        if tag == "section" and self.sections:
            self.current = self.sections.pop()

    def handle_data(self, data):
        if self.mark:
            self.text.append(data)


def report_signature(site):
    parser = ReportSignature()
    parser.feed((site / "what-changed.html").read_text())
    # Live marked decks carry their words in real slide HTML, not in the
    # parent report. Compare the same generated deck paths on both builds.
    decks = {}
    for path in sorted((site / "what-changed-decks").rglob("*.marked.html")):
        words = ReportSignature(deck=True)
        content = path.read_text()
        words.feed(content)
        decks[str(path.relative_to(site / "what-changed-decks"))] = words.marks
    return parser.pages, parser.marks, decks
