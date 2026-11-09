"""Stateless, conservative page selection for local What changed."""

import os
import re
from pathlib import Path

import yaml

PAGES = {".qmd", ".md", ".Rmd", ".ipynb"}
ASSETS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".pdf",
    ".csv",
    ".tsv",
    ".json",
    ".parquet",
}
IGNORE = {".git", ".asta", "_site", "_freeze", ".quarto", "node_modules"}


def _documents(root):
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if name not in IGNORE]
        for name in files:
            path = Path(directory) / name
            if path.suffix in PAGES:
                result[path.relative_to(root).as_posix()] = path.read_text(
                    errors="replace"
                )
    return result


def _entries(path):
    if not path.exists():
        return {}
    text = path.read_text()
    if path.suffix != ".bib":
        value = yaml.safe_load(text)
        if not isinstance(value, dict) or not isinstance(value.get("evidence"), dict):
            raise ValueError("not an evidence mapping")
        return value["evidence"]
    # Deliberately reject BibTeX constructs we cannot partition reliably.
    if re.search(r"(?i)@(string|preamble|comment)\s*[{(]", text):
        raise ValueError("bibliography macros require full comparison")
    starts = list(re.finditer(r"(?im)^\s*@([a-z]+)\s*[{(]\s*([^,\s]+)\s*,", text))
    if len(re.findall(r"(?i)@[a-z]+\s*[{(]", text)) != len(starts):
        raise ValueError("bibliography entry boundaries are ambiguous")
    if not starts or any(
        m[1].lower() in {"string", "preamble", "comment"} for m in starts
    ):
        raise ValueError("unsupported bibliography")
    entries = {}
    for i, match in enumerate(starts):
        entry = text[
            match.start() : starts[i + 1].start() if i + 1 < len(starts) else len(text)
        ]
        if entry.count("{") != entry.count("}") or match[2] in entries:
            raise ValueError("ambiguous bibliography")
        entries[match[2]] = entry
    return entries


INCLUDE = re.compile(
    r"\{\{<\s*(?:include|embed)\s+([^>]*?)\s*>\}\}"
    r"|\bchild\s*=\s*(?:c\(\s*)?[\"']([^\"']+)[\"']"
)


def _includes(page, text):
    """Files a page includes or embeds; None for a target it can't resolve."""
    for match in INCLUDE.finditer(text):
        argument = (match[1] or match[2] or "").split()
        target = argument[0].strip("\"'").split("#")[0] if argument else ""
        if not target or re.search(r"[<>{}$\\]", target):
            yield None
            continue
        base = "" if target.startswith("/") else os.path.dirname(page)
        yield os.path.normpath(os.path.join(base, target.lstrip("/"))).replace(
            os.sep, "/"
        )


def _citing(documents, key, patterns):
    """Pages citing key; None when it's mentioned but no citation is recognised."""
    found = {
        name
        for docs in documents
        for name, text in docs.items()
        if any(re.search(pattern.format(re.escape(key)), text) for pattern in patterns)
    }
    return found or None


EVIDENCE = [r"\bkey\s*=\s*[\"']?{}(?![\w:.#$%&+?<>~/-]*\w)"]
BIB = [
    r"(?<![\w@])@{}(?!\w)",
    r"@\{{{}\}}",
    r"\bcite\s*=\s*[\"']?{}(?![\w])",
    r"\bnocite\b",
]


def _evidence_citing_bib(roots, keys):
    """Evidence entries whose cite field names a changed bibliography key."""
    result = set()
    for root in roots:
        for path in root.rglob("evidence.yml"):
            if IGNORE & set(path.relative_to(root).parts):
                continue
            entries = _entries(path)
            for name, entry in entries.items():
                cite = entry.get("cite") if isinstance(entry, dict) else None
                if cite is None or not isinstance(cite, str):
                    if isinstance(entry, dict) and "cite" in entry:
                        raise ValueError("unrecognised cite field")
                    continue
                if any(key in cite for key in keys):
                    result.add(str(name))
    return result


def select_pages(after: Path, before: Path, changed: list[str]) -> list[str] | None:
    """None means compare everything. Never infer safety from a missing match."""
    if not changed:
        return None
    documents = [_documents(root) for root in (before, after)]
    all_names = set(documents[0]) | set(documents[1])
    selected = set()
    for name in set(changed):
        path = Path(name)
        if "_extensions" in path.parts or any(
            part.startswith(".") for part in path.parts
        ):
            return None
        # Make's page-list interface is whitespace separated.
        if not re.fullmatch(r"[A-Za-z0-9_/+@.\-]+", name):
            return None
        if path.suffix in PAGES:
            selected.add(name)
            if name not in documents[0] or name not in documents[1]:
                # Creation/deletion/rename may change any listing or navigation.
                return None
        elif path.name == "evidence.yml" or path.suffix == ".bib":
            try:
                old, new = (_entries(root / name) for root in (before, after))
                keys = {
                    str(k) for k in old.keys() | new.keys() if old.get(k) != new.get(k)
                }
                evidence = set()
                if path.suffix == ".bib":
                    evidence = _evidence_citing_bib((before, after), keys)
            except (OSError, ValueError, AttributeError, yaml.YAMLError):
                return None
            if not keys:
                return None
            pattern = EVIDENCE if path.suffix != ".bib" else BIB
            for key in keys:
                pages = _citing(documents, key, pattern)
                if pages is None:
                    return None
                selected |= pages
            for key in evidence:
                pages = _citing(documents, key, EVIDENCE)
                if pages is None:
                    return None
                selected |= pages
        elif path.suffix in ASSETS:
            pages = {
                page
                for docs in documents
                for page, text in docs.items()
                if name in text or path.name in text
            }
            if not pages:
                return None
            selected |= pages
        else:
            return None
    # Follow only real includes/embeds, in both revisions; a page that merely
    # links to or names a selected file renders the same.
    while True:
        added = set()
        for docs in documents:
            for page, text in docs.items():
                if page in selected:
                    continue
                for target in _includes(page, text):
                    if target is None or target in selected:
                        added.add(page)
                        break
        if not added:
            break
        selected |= added
    if not selected:
        return None
    # Includes starting with '_' aren't standalone pages. Quarto's inspect
    # provides the authoritative render set before the builds.
    return (
        sorted(
            name
            for name in selected & all_names
            if not any(part.startswith(("_", ".")) for part in Path(name).parts)
        )
        or None
    )


def paper_affected(
    project: Path, directory: str, main: str, changed: list[str]
) -> bool:
    """Build a paper only when a file in its folder or any `.bib` changed.

    The project's latexmkrc is not consulted: an older scaffold rc differs from
    the shipped one byte for byte yet only finds references.bib up the tree.
    """
    root = (project / directory).resolve()
    return any(
        (project / name).resolve().is_relative_to(root) or name.endswith(".bib")
        for name in changed
    )
