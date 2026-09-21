#!/usr/bin/env python3
"""Structural validation of `.ev` evidence spans against the evidence store.

Checks only what a script can decide without judgement: that every `.ev` key
resolves, that each entry carries a verbatim quote and a resolvable reference,
and that no stored entry is orphaned. Whether a quote actually *supports* the
claim is a reading task — see the `check-claims` skill.

Stdlib-only (PyYAML is used when present); run from the Quarto project root.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

# ---------------------------------------------------------------- YAML loading


def _load_yaml(text):
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        return _load_yaml_minimal(text)
    return yaml.safe_load(text) or {}


_KV = re.compile(r"^(?P<indent> *)(?P<key>[^\s#:][^:]*):\s*(?P<val>.*?)\s*$")
_BLOCK = re.compile(r"^[|>](?:[1-9][+-]?|[+-][1-9]?)?$")


def _scalar(raw):
    """Unquote the small set of plain YAML scalars used by workspace config."""
    if raw in ("~", "null"):
        return None
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        body = raw[1:-1]
        return body.replace('\\"', '"') if raw[0] == '"' else body.replace("''", "'")
    return raw


def _block_scalar(lines, start, parent_indent, header):
    """Read one literal/folded block while preserving the caller's line index."""
    collected = []
    content_indent = None
    index = start
    while index < len(lines):
        line = lines[index]
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if stripped and indent <= parent_indent:
            break
        if stripped and content_indent is None:
            content_indent = indent
        if not stripped:
            collected.append("")
        else:
            collected.append(line[min(content_indent or indent, len(line)) :])
        index += 1

    value = "\n".join(collected)
    if header.startswith(">"):
        value = re.sub(r"(?<!\n)\n(?!\n)", " ", value)
    if "-" not in header[1:] and value:
        value += "\n"
    return value, index


def _load_yaml_minimal(text):
    """Parse the nested block mappings this checker needs, without PyYAML.

    Deliberately narrow: flow collections and anchors are not understood. It
    does support literal/folded blocks because evidence quotes commonly use
    them and silently treating those blocks as mappings would bypass validation.
    """
    root: dict = {}
    stack = [(-1, root)]
    pending = None  # (indent, parent, key) awaiting its `- item` list
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.lstrip()
        if stripped.startswith("- ") and pending:
            indent, parent, key = pending
            if len(line) - len(stripped) > indent - 1:
                if not isinstance(parent.get(key), list):
                    parent[key] = []  # replace the empty-map placeholder
                    if stack[-1][1] is not root and stack[-1][0] == indent:
                        stack.pop()
                parent[key].append(_scalar(stripped[2:].strip()))
                continue
        pending = None
        m = _KV.match(line)
        if not m:
            continue
        indent = len(m.group("indent"))
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        key = _scalar(m.group("key").strip())
        raw = m.group("val")
        if raw.startswith("#"):
            raw = ""
        if _BLOCK.match(raw):
            parent[key], index = _block_scalar(lines, index, indent, raw)
        elif raw == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
            pending = (indent, parent, key)
        else:
            parent[key] = _scalar(raw)
    return root


# ------------------------------------------------------------------- discovery


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def discover(root):
    """Resolve store, bibliography and prose paths from _quarto.yml."""
    root = os.path.abspath(root)
    cfg = {}
    quarto = os.path.join(root, "_quarto.yml")
    if os.path.exists(quarto):
        with open(quarto, encoding="utf-8") as fh:
            cfg = _load_yaml(fh.read()) or {}

    stores = [
        p
        for p in _as_list(cfg.get("metadata-files"))
        if isinstance(p, str) and "evidence" in os.path.basename(p)
    ]
    if not stores:
        stores = sorted(
            p
            for p in glob.glob(os.path.join(root, "**", "evidence.yml"), recursive=True)
            if "_site" not in p and ".quarto" not in p
        )

    bibs = [p for p in _as_list(cfg.get("bibliography")) if isinstance(p, str)]
    if not bibs:
        bibs = sorted(glob.glob(os.path.join(root, "*.bib")))

    render = [
        p
        for p in _as_list((cfg.get("project") or {}).get("render"))
        if isinstance(p, str)
    ]
    includes = [p for p in render if not p.startswith("!")] or ["**/*.qmd"]
    excludes = [p[1:] for p in render if p.startswith("!")]
    qmds = {
        os.path.abspath(path)
        for pattern in includes
        for path in glob.glob(os.path.join(root, pattern), recursive=True)
        if path.endswith(".qmd")
    }
    for pattern in excludes:
        excluded = [
            os.path.abspath(path)
            for path in glob.glob(os.path.join(root, pattern), recursive=True)
        ]
        qmds = {
            path
            for path in qmds
            if not any(
                path == item or path.startswith(item.rstrip(os.sep) + os.sep)
                for item in excluded
            )
        }
    qmds = sorted(
        path
        for path in qmds
        if "_site" not in os.path.relpath(path, root).split(os.sep)
        and ".quarto" not in os.path.relpath(path, root).split(os.sep)
    )

    def absolute(paths):
        return [
            os.path.abspath(p if os.path.isabs(p) else os.path.join(root, p))
            for p in paths
        ]

    return absolute(stores), absolute(bibs), qmds


def bib_keys(paths):
    keys = set()
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            keys |= set(re.findall(r"^\s*@\w+\s*\{\s*([^,\s]+)\s*,", fh.read(), re.M))
    return keys


# ------------------------------------------------------------- span extraction

# `[claim text]{.ev key="…"}` — one level of nested brackets (links, citations)
# is tolerated inside the claim.
SPAN = re.compile(r"\[(?P<text>(?:[^\[\]]|\[[^\[\]]*\])*)\]\{(?P<attrs>[^{}]*)\}")
ATTR = re.compile(
    r'(?P<name>[A-Za-z_][\w-]*)\s*=\s*(?P<q>["\'])(?P<val>.*?)(?P=q)', re.S
)
FENCE = re.compile(r"^ {0,3}(?P<mark>`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(?P<mark>`+).*?(?P=mark)")


def _blank_nonprose(text):
    """Blank comments and code while preserving offsets and line numbers."""
    chars = list(text)

    def blank(start, end):
        for pos in range(start, end):
            if chars[pos] != "\n":
                chars[pos] = " "

    for match in re.finditer(r"<!--.*?-->", text, re.S):
        blank(*match.span())

    masked = "".join(chars)
    offset = 0
    fence = None
    for line in masked.splitlines(keepends=True):
        match = FENCE.match(line)
        if fence:
            blank(offset, offset + len(line))
            if (
                match
                and match.group("mark")[0] == fence[0]
                and len(match.group("mark")) >= len(fence)
                and not line[match.end() :].strip()
            ):
                fence = None
        elif match:
            fence = match.group("mark")
            blank(offset, offset + len(line))
        offset += len(line)

    masked = "".join(chars)
    for match in INLINE_CODE.finditer(masked):
        blank(*match.span())
    return "".join(chars)


def spans(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    prose = _blank_nonprose(text)
    for m in SPAN.finditer(prose):
        attrs = m.group("attrs")
        if not re.search(r"(^|\s)\.ev(\s|$)", attrs):
            continue
        yield {
            "line": prose.count("\n", 0, m.start()) + 1,
            "claim": " ".join(m.group("text").split()),
            "attrs": {a.group("name"): a.group("val") for a in ATTR.finditer(attrs)},
        }


# ---------------------------------------------------------------------- checks


class Report:
    def __init__(self):
        self.errors = []

    def error(self, path, line, message):
        self.errors.append((path, line, message))

    def emit(self):
        for path, line, message in self.errors:
            where = f"{path}:{line}" if line else path
            loc = f" file={path},line={line}" if line else f" file={path}"
            print(f"::error{loc}::{message}")
            print(f"  {where}: {message}", file=sys.stderr)
        return 1 if self.errors else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Quarto project root (default: .)")
    parser.add_argument(
        "--allow-orphans",
        action="store_true",
        help="do not fail on store entries no prose references",
    )
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    stores, bibs, qmds = discover(root)
    report = Report()

    store = {}
    origin = {}
    for path in stores:
        rel = os.path.relpath(path, root)
        if not os.path.exists(path):
            report.error(rel, 0, f"evidence store not found: {rel}")
            continue
        with open(path, encoding="utf-8") as fh:
            data = _load_yaml(fh.read()) or {}
        entries = data.get("evidence") or {}
        if not isinstance(entries, dict):
            report.error(
                rel, 0, "evidence store: top-level `evidence:` must be a mapping"
            )
            continue
        for key, entry in entries.items():
            if key in store:
                report.error(
                    rel,
                    0,
                    f'evidence key "{key}" is defined twice (also in {origin[key]})',
                )
            store[key] = entry if isinstance(entry, dict) else {}
            origin[key] = rel

    keys = bib_keys(bibs)
    used = set()
    n_spans = 0

    for path in qmds:
        rel = os.path.relpath(path, root)
        for span in spans(path):
            n_spans += 1
            attrs, line = span["attrs"], span["line"]
            claim = span["claim"][:60] or "(empty claim text)"
            key = attrs.get("key")
            if key:
                used.add(key)
                if key not in store:
                    report.error(
                        rel,
                        line,
                        f'.ev key "{key}" has no entry in the evidence store '
                        f'(claim: "{claim}")',
                    )
                    continue
            entry = dict(store.get(key, {})) if key else {}
            entry.update({k: v for k, v in attrs.items() if k != "key"})
            if not span["claim"].strip():
                report.error(rel, line, f'.ev span has empty claim text (key "{key}")')
            if not str(entry.get("quote") or "").strip():
                report.error(
                    rel,
                    line,
                    f'.ev evidence for "{key or claim}" has no verbatim quote',
                )
            cite = str(entry.get("cite") or "").strip()
            if cite:
                if cite not in keys:
                    report.error(
                        rel,
                        line,
                        f'.ev evidence for "{key or claim}" cites "{cite}", '
                        f"which is not a key in "
                        f"{', '.join(os.path.relpath(b, root) for b in bibs) or 'the bibliography'}",
                    )
            elif not (
                str(entry.get("source") or "").strip()
                and str(entry.get("url") or "").strip()
            ):
                report.error(
                    rel,
                    line,
                    f'.ev evidence for "{key or claim}" has no reference: '
                    "set `cite` to a bibliography key, or both `source` and `url`",
                )

    if not args.allow_orphans:
        for key in sorted(set(store) - used):
            report.error(
                origin[key],
                0,
                f'evidence entry "{key}" is not referenced by any .ev span '
                "(remove it, or reference it from the prose)",
            )

    status = report.emit()
    if status:
        print(f"::error::check-evidence: {len(report.errors)} problem(s) found")
    else:
        print(
            f"✓ evidence OK ({n_spans} claim span(s), {len(used)} key(s), "
            f"{len(store)} store entr(ies))"
        )
    return status


if __name__ == "__main__":
    sys.exit(main())
