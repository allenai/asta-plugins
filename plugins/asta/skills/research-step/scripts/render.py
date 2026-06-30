#!/usr/bin/env python3
"""render.py — the generic Jinja2 rendering engine for research-step.

All human-facing wording lives in `assets/templates/report/*.md.j2`, not here. Each
report-section template may carry YAML front-matter and a Jinja body. This module is
the generic compiler: `compile-report.py` imports it and calls `render_template_file`
to render each section with its context plus a few helpers. No task-specific logic.
"""

from __future__ import annotations

import re
from pathlib import Path

FRONT_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def _require_jinja():
    try:
        import jinja2  # noqa: F401
    except ImportError:
        raise SystemExit("render: python3 cannot import jinja2 — run the init workflow")
    return jinja2


def split_front_matter(text):
    """Return (meta_dict, body) from a template that starts with --- front-matter."""
    import yaml

    m = FRONT_RE.match(text)
    if not m:
        return {}, text
    meta = yaml.safe_load(m.group(1)) or {}
    return meta, text[m.end():]


# --- helpers exposed to templates (keep tiny; templates do the rest in Jinja) ---

def _link(label, target):
    label = "" if label is None else str(label)
    return f"[{label}]({target})" if target else label


def _artifacts(output):
    """Markdown bullet list of a task's artifacts, by their first file part uri."""
    lines = []
    for art in (output or {}).get("artifacts") or []:
        name = art.get("name") or art.get("artifactId") or "artifact"
        kind = (art.get("metadata") or {}).get("type", "")
        label = f"{name} ({kind})" if kind else name
        uri = None
        for part in art.get("parts") or []:
            if part.get("kind") == "file":
                uri = (part.get("file") or {}).get("uri")
                if uri:
                    break
        lines.append(f"- {_link(label, uri)}")
    return "\n".join(lines)


def _env(trim=True):
    jinja2 = _require_jinja()
    env = jinja2.Environment(
        # move the comment delimiter off "{#" so pandoc heading anchors ({#id}) pass through
        comment_start_string="{=#",
        comment_end_string="#=}",
        trim_blocks=trim,
        lstrip_blocks=trim,
        keep_trailing_newline=True,
        undefined=jinja2.ChainableUndefined,  # missing optional fields render empty, no crash
        autoescape=False,
    )
    import os
    env.globals.update(link=_link, artifacts=_artifacts, exists=lambda p: bool(p) and os.path.exists(p))
    # |md — make any value safe inside a markdown table cell (escape pipes, flatten newlines)
    env.filters["md"] = lambda s: ("" if s is None else str(s)).replace("|", "\\|").replace("\n", " ").strip()

    def _comma(n):
        try:
            return f"{int(n):,}"
        except (TypeError, ValueError):
            return "" if n is None else str(n)

    env.filters["comma"] = _comma

    def _clean(s):
        s = "" if s is None else str(s)
        s = re.sub(r"\s*\(?(?:Registered as )?Asta document [A-Za-z0-9_-]+\)?\.?", "", s)
        return s.strip()

    env.filters["clean"] = _clean

    def _sent(s):
        # trim to the last complete sentence (source text is sometimes capped mid-word)
        s = ("" if s is None else str(s)).strip()
        ms = list(re.finditer(r"\.(?:\s|$)", s))
        if ms and ms[-1].end() > 40:
            return s[: ms[-1].end()].strip()
        return (s.rstrip(" ,;:-(") + "…") if s else s

    env.filters["sent"] = _sent
    return env


def render_template_file(path, **context):
    """Render a report section template with context. Uses a NON-trimming env so the
    explicit blank lines that separate headings/paragraphs survive (these templates are
    prose, not tables, so block-tag newlines must not be eaten)."""
    _meta, body = split_front_matter(Path(path).read_text())
    return _env(trim=False).from_string(body).render(**context).strip() + "\n"
