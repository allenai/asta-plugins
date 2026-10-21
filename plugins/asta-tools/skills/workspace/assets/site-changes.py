"""Let a rendered site show its changes against an earlier version.

Writes `<new>/_changes/`: which pages changed, each changed page's content with
its changes marked, and a script every page loads. Each page then shows its
changes in place, as in Google Docs or Overleaf, under a line that says what's
marked and hides it; the sidebar marks which pages changed, and "All changes"
opens the cross-page What changed report. The comparison is what What changed
already computes, page by page, so a pull request's preview and
`asta workspace what-changed <ref>` run it right after that report.

    python3 site-changes.py --new NEW_SITE --compare "in this pull request" OLD_SITE --on
"""

import argparse
import html
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Loading the report's code beside this file must leave no __pycache__ in a
# project's scripts folder.
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("what_changed", HERE / "what-changed.py")
wc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wc)

MARK = "<!-- site-changes -->"

# The report shows pages inside its own page, so it keeps only inert markup.
# Here a page's marked content takes the place of its own, on the project's
# own site, so it also keeps what the page relies on: its anchors, keyboard
# focus, and the data its callouts, tabs and citations read. Scripts and
# event handlers still go.
PAGE_ATTRS = wc.GLOBAL_SAFE_ATTRS | {"id", "tabindex", "style"}


class _PageFragmentParser(wc._SafeFragmentParser):
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self.drop_stack or tag in wc.DROP_CONTENT_TAGS:
            if tag in wc.DROP_CONTENT_TAGS:
                self.drop_stack.append(tag)
            return
        if tag not in wc.SAFE_TAGS:
            return
        allowed = PAGE_ATTRS | wc.TAG_SAFE_ATTRS.get(tag, set())
        clean = []
        for name, value in attrs:
            name = name.lower()
            if name not in allowed and not name.startswith(("aria-", "data-")):
                continue
            if value is None:
                clean.append(name)
            elif name not in wc.URL_ATTRS or wc.safe_url(value):
                clean.append(f'{name}="{html.escape(value, quote=True)}"')
        self.out.append(f"<{tag}{' ' + ' '.join(clean) if clean else ''}>")


def page_fragment(content):
    parser = _PageFragmentParser()
    parser.feed(content)
    parser.close()
    return "".join(parser.out)


def rendered_page(path):
    """A page Quarto rendered, not an HTML file the site copies through.

    A paper's page is left out too: its paper's own entry, the marked PDF,
    says what changed, not a diff of the viewer around it.
    """
    try:
        with open(path, encoding="utf-8") as f:
            doc = f.read()
    except (OSError, UnicodeDecodeError):
        return False
    return (
        'name="generator" content="quarto-' in doc and "data-paper-preview" not in doc
    )


# The site's own pages only, for the marking and the overview alike: copied
# HTML (generated run reports, say) isn't what a reader browses as the site.
_all_pages = wc.list_pages
wc.list_pages = lambda root, *rest, **kw: {
    rel: path
    for rel, path in _all_pages(root, *rest, **kw).items()
    if rendered_page(path)
}

STYLE = """
.wc-scope { --wc-ins-bg: #d7f5dd; --wc-ins-line: #1a7f37; --wc-ins-fg: #032b13;
  --wc-del-bg: #ffd7d5; --wc-del-line: #cf222e; --wc-del-fg: #40100c; }
body.quarto-dark .wc-scope { --wc-ins-bg: #12341f; --wc-ins-line: #3fb950; --wc-ins-fg: #d7ffe4;
  --wc-del-bg: #4a1512; --wc-del-line: #f85149; --wc-del-fg: #ffdcd7; }
.wc-scope ins { background: var(--wc-ins-bg); color: var(--wc-ins-fg); text-decoration: none;
  border-inline-start: 2px solid var(--wc-ins-line); border-radius: 2px; padding: 0 .1em; }
.wc-scope del { background: var(--wc-del-bg); color: var(--wc-del-fg);
  text-decoration: line-through; text-decoration-color: var(--wc-del-line);
  text-decoration-thickness: 2px; border-radius: 2px; padding: 0 .1em; }
.wc-scope ins img { outline: 3px solid var(--wc-ins-line); }
.wc-scope del img { outline: 3px solid var(--wc-del-line); opacity: .6; }
/* Marked lines run longer, so a hidden quote popover can reach past a phone's
   edge; out of layout until shown, it never makes the page scroll sideways. */
.wc-scope .ev-pop { display: none; }
.wc-scope .ev:hover > .ev-pop, .wc-scope .ev:focus > .ev-pop,
.wc-scope .ev:focus-within > .ev-pop { display: block; }
/* Off, the switch is one icon among the sidebar's tools, after the title and
   before nothing else, so the outline still comes first. */
.sc-icon { border: 0; background: transparent; color: inherit; cursor: pointer;
  font-size: inherit; line-height: inherit; }
.sc-icon[aria-pressed="true"] { color: #2f9e57; }
.sc-icon:focus-visible, .sc-hide:focus-visible { outline: 2px solid var(--bs-link-color);
  outline-offset: 2px; }
/* On, one line at the top of the page says what's marked, against which
   version, and turns it off again. */
.sc-note { font-size: .875rem; color: var(--bs-secondary-color); margin: 0 0 1rem;
  padding: .35rem .7rem; border-left: 3px solid #2f9e57; }
.sc-hide { font: inherit; padding: 0; border: 0; background: transparent;
  color: var(--bs-link-color); text-decoration: underline; cursor: pointer; }
.sc-offer { border-left-color: var(--bs-border-color); }
.sc-on #quarto-sidebar a.sc-changed::after { content: "\\25CF"; margin-left: .4em;
  font-size: .7em; color: #2f9e57; vertical-align: middle; }
.sc-on #quarto-sidebar a.sc-new::after { content: "new"; margin-left: .4em; font-size: .7em;
  padding: 0 .4em; border-radius: 999px; background: #2f9e57; color: #fff; vertical-align: middle; }
"""

SCRIPT = r"""
(() => {
  const script = document.currentScript;
  const base = new URL('.', script.src);
  const root = new URL('..', base);
  const relOf = url => {
    if (url.origin !== root.origin || !url.pathname.startsWith(root.pathname)) return null;
    let rel = decodeURIComponent(url.pathname.slice(root.pathname.length));
    return rel === '' || rel.endsWith('/') ? rel + 'index.html' : rel;
  };
  const rel = relOf(new URL(location.href));
  const load = id => fetch(new URL(id + '/manifest.json', base)).then(r => r.json());
  fetch(new URL('index.json', base)).then(r => r.json()).then(async index => {
    // Nothing changed, and there's no switch.
    const choice = index.comparisons.find(c => c.total);
    if (!choice) return;
    // Hiding is remembered for this site and this comparison only, so that
    // it never carries into another one served at the same address.
    const key = 'site-changes:' + root.pathname + ':' + choice.label;
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch (e) {}
    let shown = typeof saved.on === 'boolean' ? saved.on : !!index.on;
    const m = await load(choice.id);
    let page, papers, paper;
    const main = document.querySelector('#quarto-document-content');
    // The page's own elements, kept as they are, so that putting them back
    // keeps what the site's scripts attached to them (citation hovers, say).
    const original = main ? [...main.childNodes] : [];
    const restore = () => main.replaceChildren(...original);
    const marked = {};
    const save = () => {
      try { localStorage.setItem(key, JSON.stringify({ on: shown })); } catch (e) {}
    };
    // One mark per page: its first link, not each link into its sections.
    const markSidebar = () => {
      page = m.pages[rel];
      papers = new Map((m.papers || []).map(p => [p.page, p]));
      paper = papers.get(rel);
      const seen = new Set();
      for (const a of document.querySelectorAll('#quarto-sidebar a[href]')) {
        a.classList.remove('sc-changed', 'sc-new');
        if (a.getAttribute('href').startsWith('#') || !a.textContent.trim()) continue;
        const target = relOf(new URL(a.getAttribute('href'), location.href));
        if (!target || seen.has(target)) continue;
        seen.add(target);
        if (m.pages[target]?.state === 'new') a.classList.add('sc-new');
        else if (m.pages[target] || papers.has(target)) a.classList.add('sc-changed');
      }
    };
    const control = document.createElement('div');
    // Off, it's one icon beside the site's other tools, so the outline comes
    // first; on, the line at the top of the page holds the rest.
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'sc-icon quarto-navigation-tool px-1';
    toggle.innerHTML = '<i class="bi bi-file-diff"></i>';
    const tools = document.querySelector('#quarto-sidebar .sidebar-tools-main');
    if (tools) tools.append(toggle);
    const describe = () => {
      const label = (shown ? 'Hide changes ' : 'Show changes ') + choice.label;
      toggle.title = label;
      toggle.setAttribute('aria-label', label);
    };
    const allLink = () => {
      const a = document.createElement('a');
      a.href = new URL(m.overview, root).href;
      a.textContent = 'All changes (' + m.count + ')';
      return a;
    };
    let all = allLink();
    const hide = document.createElement('button');
    hide.type = 'button';
    hide.className = 'sc-hide';
    hide.textContent = 'Hide';
    // Without a sidebar to hold the icon, the page offers the switch itself.
    const offer = document.createElement('p');
    offer.className = 'sc-note sc-offer';
    const show = document.createElement('button');
    show.type = 'button';
    show.className = 'sc-hide';
    show.textContent = 'Show changes ' + choice.label;
    offer.append(show);
    const note = document.createElement('p');
    note.className = 'sc-note';
    const status = { set textContent(text) {
      note.replaceChildren();
      offer.remove();
      if (!text) {
        note.remove();
        if (!tools && main) main.prepend(offer);
        return;
      }
      note.append('Changes ' + choice.label + ': ' + text + ' · ', allLink(), ' · ', hide);
      if (main) main.prepend(note);
    } };
    // The paper page's own switch shows the paper with its changes marked.
    const paperMode = on => {
      const pick = () => {
        const modes = document.querySelector('.paper-modes');
        if (!modes || modes.hidden) return false;
        modes.querySelector(`[data-file="${on ? 'what-changed.pdf' : 'main.pdf'}"]`)?.click();
        return true;
      };
      if (!pick()) {
        const wait = new MutationObserver(() => { if (pick()) wait.disconnect(); });
        wait.observe(document.body, { subtree: true, attributes: true, attributeFilter: ['hidden'] });
        setTimeout(() => wait.disconnect(), 5000);
      }
    };
    const apply = async on => {
      toggle.setAttribute('aria-pressed', String(on));
      document.documentElement.classList.toggle('sc-on', on);
      const fresh = allLink();
      all.replaceWith(fresh);
      all = fresh;
      if (main && main.querySelector('.wc-scope') && !(on && page && page.marks)) restore();
      if (paper || papers.size && document.querySelector('[data-paper-preview]')) {
        if (paper?.marked) paperMode(on);
        else paperMode(false);
        status.textContent = !on ? '' : !paper ? 'no changes to the paper'
          : paper.marked ? 'the paper with its changes marked'
          : 'files in the paper’s folder changed, not its LaTeX, so nothing is marked';
      } else if (page && page.marks && main) {
        if (on) {
          const text = marked[choice.id] ?? (marked[choice.id] = await fetch(
            new URL(choice.id + '/pages/' + rel + '.txt', base)).then(r => r.text()));
          // Hidden while the marks were loading: the later choice stands.
          if (shown !== on) return;
          main.innerHTML = '<div class="wc-scope">' + text + '</div>';
          // Swapped-in content arrives as source; the page's math typesetter
          // ran once at load, so it runs again on what's now shown.
          if (window.MathJax?.typesetPromise) {
            window.MathJax.typesetClear?.([main]);
            window.MathJax.typesetPromise([main]).catch(() => {});
          }
          // As the evidence script does for the page's own claims: a quote
          // that would pass the window's right edge opens leftward.
          for (const ev of main.querySelectorAll('.ev')) {
            const place = () => {
              ev.classList.remove('ev-flip');
              const card = ev.querySelector('.ev-card') || ev.querySelector('.ev-pop');
              if (card && card.getBoundingClientRect().right > document.documentElement.clientWidth - 8)
                ev.classList.add('ev-flip');
            };
            ev.addEventListener('mouseenter', place);
            ev.addEventListener('focusin', place);
          }
        } else restore();
        status.textContent = on ? page.marks + (page.marks === 1 ? ' change' : ' changes') + ' marked on this page' : '';
      } else {
        status.textContent = !on ? '' : page?.state === 'new' ? 'a new page'
          : page ? 'this page changed, but draws its content with scripts, so it isn’t marked'
          : 'no changes on this page';
      }
      describe();
    };
    const flip = () => {
      shown = !shown;
      save();
      apply(shown);
    };
    for (const button of [toggle, hide, show]) button.addEventListener('click', flip);
    markSidebar();
    apply(shown);
  });
})();
"""


def marks(fragment):
    return len(re.findall(r"<(?:ins|del)\b", fragment))


def compare(old_root, new_root):
    """Each page's state since the old site, and its marked content."""
    old_pages = wc.list_pages(old_root)
    new_pages = wc.list_pages(new_root)
    pages, fragments = {}, {}
    for rel, path in sorted(new_pages.items()):
        new_doc = Path(path).read_text(encoding="utf-8")
        title = wc.page_title(new_doc, rel)
        if rel not in old_pages:
            pages[rel] = {"state": "new", "title": title}
            continue
        old_doc = Path(old_pages[rel]).read_text(encoding="utf-8")
        old_c = wc.normalize(wc.extract_main(old_doc))
        new_c = wc.normalize(wc.extract_main(new_doc))
        if re.sub(r"\s+", " ", old_c).strip() == re.sub(r"\s+", " ", new_c).strip():
            continue
        if wc.is_self_contained(old_c) or wc.is_self_contained(new_c):
            pages[rel] = {"state": "changed", "title": title}
            continue
        if wc.markup_signature(old_c) == wc.markup_signature(new_c):
            continue
        body, changed = wc.diff_content(page_fragment(old_c), page_fragment(new_c))
        if not changed:
            continue
        pages[rel] = {"state": "changed", "title": title, "marks": marks(body)}
        fragments[rel] = body
    removed = sorted(set(old_pages) - set(new_pages))
    return pages, fragments, removed


def changed_papers(new_root):
    papers = []
    previews = Path(new_root) / "paper-previews"
    for manifest in previews.rglob("preview.json") if previews.is_dir() else []:
        try:
            state = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(state, dict)
            and state.get("changed")
            and not state.get("removed")
        ):
            directory = manifest.parent.relative_to(previews).as_posix()
            papers.append(
                {
                    "page": f"{directory}/html/index.html",
                    "marked": bool(state.get("diff")),
                }
            )
    return papers


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--new", required=True, type=Path)
    ap.add_argument(
        "--compare",
        nargs=2,
        required=True,
        metavar=("LABEL", "OLD_SITE"),
        help='what the site is compared with, as the page names it ("in this pull '
        "request\"), and that version's rendered site",
    )
    ap.add_argument("--title", default="Site")
    ap.add_argument(
        "--on", action="store_true", help="show changes until a reader turns them off"
    )
    args = ap.parse_args()
    label, old = args.compare
    new_root = args.new.resolve()
    out = new_root / "_changes"
    shutil.rmtree(out, ignore_errors=True)
    pages, fragments, removed = compare(str(Path(old).resolve()), str(new_root))
    # A preview's paper PDFs were built against the same version.
    papers = changed_papers(new_root)
    # As text, not pages: their links are relative to the page they mark, so
    # a site's own link check must not read them from here.
    for rel, body in fragments.items():
        target = out / "c0" / "pages" / f"{rel}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    # The overview is the What changed report the preview or CLI just made.
    overview = "what-changed.html"
    if not (new_root / overview).exists():
        report = wc.build(
            str(Path(old).resolve()), str(new_root), "", f"{args.title} {label}"
        )
        (new_root / overview).write_text(report, encoding="utf-8")
    count = len(pages) + len(removed) + len(papers)
    manifest = {
        "label": label,
        "overview": overview,
        "total": count,
        "count": f"{count} page{'s' if count != 1 else ''}",
        "pages": pages,
        "papers": papers,
        "removed": removed,
    }
    (out / "c0").mkdir(parents=True, exist_ok=True)
    (out / "c0" / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    index = {
        "on": args.on,
        "comparisons": [{"id": "c0", "label": label, "total": count}],
    }
    print(
        f"site-changes: {label}: {len(pages)} pages, {len(papers)} papers, {len(removed)} removed"
    )
    (out / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    (out / "changes.js").write_text(SCRIPT, encoding="utf-8")
    (out / "changes.css").write_text(STYLE, encoding="utf-8")
    # Every page the site renders gets the bar, its paper pages included.
    for rel, path in _all_pages(str(new_root)).items():
        doc = Path(path).read_text(encoding="utf-8")
        if MARK in doc or "</body>" not in doc or 'content="quarto-' not in doc:
            continue
        up = "../" * rel.count("/")
        tags = (
            f'{MARK}<link rel="stylesheet" href="{up}_changes/changes.css">'
            f'<script src="{up}_changes/changes.js" defer></script>'
        )
        # The document's own closing tag, the last one, never one quoted in a script.
        end = doc.rfind("</body>")
        Path(path).write_text(doc[:end] + tags + doc[end:], encoding="utf-8")


if __name__ == "__main__":
    main()
