#!/usr/bin/env python3
"""Structural validation of `.ev` evidence spans against the evidence store.

Checks only what a script can decide without judgement: that every `.ev` key
resolves, that each entry carries a verbatim quote and a resolvable reference,
and that no stored entry is orphaned. Whether a quote actually *supports* the
claim is a reading task — see the `check-claims` skill.

Stdlib-only (PyYAML is used when present); run from the Quarto project root.
Put `.ev` examples in inline or fenced code; indented code is treated as prose.
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

    class UniqueKeyLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            self.flatten_mapping(node)
            mapping = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if key in mapping:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        f"duplicate YAML key {key!r}",
                        key_node.start_mark,
                    )
                mapping[key] = self.construct_object(value_node, deep=deep)
            return mapping

    try:
        result = yaml.load(text, Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML: {exc}") from exc
    if result is None:
        return {}
    if not isinstance(result, dict):
        raise ValueError("top-level YAML document must be a mapping")
    return result


_KV = re.compile(r"^(?P<indent> *)(?!-\s)(?P<key>[^\s#:][^:]*):\s*(?P<val>.*?)\s*$")
_BLOCK = re.compile(r"^[|>](?:[1-9][+-]?|[+-][1-9]?)?$")


def _scalar(raw):
    """Unquote the small set of plain YAML scalars used by workspace config."""
    if raw[:1] not in "\"'":
        raw = re.sub(r"\s+#.*$", "", raw).rstrip()
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
        if stripped.startswith("- ") and len(line) == len(stripped):
            raise ValueError("top-level YAML document must be a mapping")
        pending = None
        m = _KV.match(line)
        if not m:
            continue
        indent = len(m.group("indent"))
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        key = _scalar(m.group("key").strip())
        if key in parent:
            raise ValueError(f"duplicate YAML key {key!r} on line {index}")
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
            if raw.startswith(("[", "{")):
                raise ValueError(
                    "flow-style YAML requires PyYAML; use block mappings/lists instead"
                )
            parent[key] = _scalar(raw)
    return root


# ------------------------------------------------------------------- discovery


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _load_yaml_file(path, root, report):
    rel = os.path.relpath(path, root)
    try:
        with open(path, encoding="utf-8") as fh:
            return _load_yaml(fh.read())
    except (OSError, ValueError) as exc:
        report.error(rel, 0, str(exc))
        return {}


def _is_generated(path, root):
    components = os.path.relpath(path, root).split(os.sep)
    return "_site" in components or ".quarto" in components


def discover(root, report=None):
    """Resolve store, bibliography and prose paths from _quarto.yml."""
    root = os.path.abspath(root)
    real_root = os.path.realpath(root)
    report = report or Report()
    cfg = {}
    quarto = os.path.join(root, "_quarto.yml")
    if os.path.exists(quarto):
        cfg = _load_yaml_file(quarto, root, report)

    stores = [
        p
        for p in _as_list(cfg.get("metadata-files"))
        if isinstance(p, str) and "evidence" in os.path.basename(p)
    ]
    if not stores:
        stores = sorted(
            p
            for p in glob.glob(os.path.join(root, "**", "evidence.yml"), recursive=True)
            if not _is_generated(p, root)
        )

    bibs = [p for p in _as_list(cfg.get("bibliography")) if isinstance(p, str)]
    if not bibs:
        bibs = sorted(glob.glob(os.path.join(root, "*.bib")))

    project = cfg.get("project") or {}
    if not isinstance(project, dict):
        report.error("_quarto.yml", 0, "`project:` must be a mapping")
        project = {}
    render = [p for p in _as_list(project.get("render")) if isinstance(p, str)]
    includes = [p for p in render if not p.startswith("!")] or ["**/*.qmd"]
    excludes = [p[1:] for p in render if p.startswith("!")]

    def project_glob(pattern):
        if os.path.isabs(pattern):
            report.error(
                "_quarto.yml",
                0,
                f"`project.render` pattern must be relative to the project root: {pattern}",
            )
            return []
        target = os.path.abspath(os.path.join(root, pattern))
        if os.path.commonpath((root, target)) != root:
            report.error(
                "_quarto.yml",
                0,
                f"`project.render` pattern escapes the project root: {pattern}",
            )
            return []
        return glob.glob(target, recursive=True)

    prose_paths = {
        os.path.abspath(path)
        for pattern in includes
        for path in project_glob(pattern)
        if os.path.splitext(path)[1].lower() in {".qmd", ".md"}
        and os.path.commonpath((real_root, os.path.realpath(path))) == real_root
    }
    for pattern in excludes:
        excluded = [
            os.path.abspath(path)
            for path in project_glob(pattern)
            if os.path.commonpath((real_root, os.path.realpath(path))) == real_root
        ]
        prose_paths = {
            path
            for path in prose_paths
            if not any(
                path == item or path.startswith(item.rstrip(os.sep) + os.sep)
                for item in excluded
            )
        }
    prose_paths = sorted(path for path in prose_paths if not _is_generated(path, root))

    # Quarto render lists omit partials pulled in with `{{< include ... >}}`.
    # Follow those includes transitively so their spans count as real uses.
    pending = list(prose_paths)
    seen = set(prose_paths)
    include_re = re.compile(
        r"""\{\{<\s*include\s+(?:"([^"]+)"|'([^']+)'|([^\s>]+))\s*>\}\}"""
    )
    while pending:
        source = pending.pop()
        try:
            with open(source, encoding="utf-8") as fh:
                text = _blank_nonprose(fh.read())
        except OSError:
            continue
        for match in include_re.finditer(text):
            target = next(group for group in match.groups() if group is not None)
            path = os.path.abspath(os.path.join(os.path.dirname(source), target))
            if (
                os.path.splitext(path)[1].lower() in {".qmd", ".md"}
                and os.path.commonpath((real_root, os.path.realpath(path))) == real_root
                and os.path.isfile(path)
                and not _is_generated(path, root)
                and path not in seen
            ):
                seen.add(path)
                pending.append(path)
    prose_paths = sorted(seen)

    def absolute(paths):
        return [
            os.path.abspath(p if os.path.isabs(p) else os.path.join(root, p))
            for p in paths
        ]

    return absolute(stores), absolute(bibs), prose_paths


def bib_keys(paths):
    keys = set()
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            text = "\n".join(line for line in fh if not line.lstrip().startswith("%"))
            keys |= set(re.findall(r"^\s*@\w+\s*\{\s*([^,\s}]+)\s*(?:,|})", text, re.M))
    return keys


# ------------------------------------------------------------- span extraction

# `[claim text]{.ev key="…"}` — one level of nested brackets (links, citations)
# is tolerated inside the claim.
SPAN = re.compile(r"\[(?P<text>(?:[^\[\]]|\[[^\[\]]*\])*)\]\{(?P<attrs>[^{}]*)\}")
ATTR = re.compile(
    r"(?P<name>[A-Za-z_][\w-]*)\s*=\s*"
    r'(?:(?P<q>["\'])(?P<val>.*?)(?P=q)|(?P<uval>[^\s}"\']+))',
    re.S,
)
FENCE = re.compile(r"^ {0,3}(?P<mark>`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(?P<mark>`+).*?(?P=mark)", re.S)


def _blank_nonprose(text, warning=None):
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
    fence_line = 0
    for line_number, line in enumerate(masked.splitlines(keepends=True), start=1):
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
            fence_line = line_number
            blank(offset, offset + len(line))
        offset += len(line)

    if fence and warning:
        warning(fence_line, "unclosed fenced code block; evidence after it was skipped")

    masked = "".join(chars)
    for match in INLINE_CODE.finditer(masked):
        blank(*match.span())
    return "".join(chars)


def spans(path, report=None, rel=None):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    prose = _blank_nonprose(
        text,
        (lambda line, message: report.warning(rel or str(path), line, message))
        if report
        else None,
    )
    for m in SPAN.finditer(prose):
        attrs = m.group("attrs")
        if not re.search(r"(^|\s)\.ev(\s|$)", attrs):
            continue
        yield {
            "line": prose.count("\n", 0, m.start()) + 1,
            "claim": " ".join(m.group("text").split()),
            "attrs": {
                a.group("name"): (
                    a.group("val") if a.group("val") is not None else a.group("uval")
                )
                for a in ATTR.finditer(attrs)
            },
        }


# ---------------------------------------------------------------------- checks


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, path, line, message):
        self.errors.append((path, line, message))

    def warning(self, path, line, message):
        self.warnings.append((path, line, message))

    @staticmethod
    def _workflow_escape(value, *, property_value=False):
        escaped = (
            str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        )
        if property_value:
            escaped = escaped.replace(":", "%3A").replace(",", "%2C")
        return escaped

    def _annotation(self, level, path, line, message):
        location = f"file={self._workflow_escape(path, property_value=True)}"
        if line:
            location += f",line={line}"
        print(f"::{level} {location}::{self._workflow_escape(message)}")

    def emit(self):
        for path, line, message in self.warnings:
            where = f"{path}:{line}" if line else path
            if os.environ.get("GITHUB_ACTIONS"):
                self._annotation("warning", path, line, message)
            print(f"  {where}: warning: {message}", file=sys.stderr)
        for path, line, message in self.errors:
            where = f"{path}:{line}" if line else path
            if os.environ.get("GITHUB_ACTIONS"):
                self._annotation("error", path, line, message)
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
    report = Report()
    stores, bibs, qmds = discover(root, report)

    store = {}
    origin = {}
    for path in stores:
        rel = os.path.relpath(path, root)
        if not os.path.exists(path):
            report.error(rel, 0, f"evidence store not found: {rel}")
            continue
        data = _load_yaml_file(path, root, report)
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
            if not isinstance(entry, dict):
                report.error(rel, 0, f'evidence entry "{key}" must be a mapping')
                entry = {}
            store[key] = entry
            origin[key] = rel

    keys = bib_keys(bibs)
    used = set()
    n_spans = 0

    for path in qmds:
        rel = os.path.relpath(path, root)
        for span in spans(path, report, rel):
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
        message = f"check-evidence: {len(report.errors)} problem(s) found"
        print(f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else message)
    else:
        print(
            f"✓ evidence OK ({n_spans} claim span(s), {len(used)} key(s), "
            f"{len(store)} store entr(ies))"
        )
    return status


if __name__ == "__main__":
    sys.exit(main())
