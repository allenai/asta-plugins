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
    starts = list(re.finditer(r"(?im)^\s*@([a-z]+)\s*[{(]\s*([^,\s]+)\s*,", text))
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


def select_pages(after: Path, before: Path, changed: list[str]) -> list[str] | None:
    """None means compare everything. Never infer safety from a missing match."""
    if not changed:
        return None
    documents = [_documents(root) for root in (before, after)]
    all_names = set(documents[0]) | set(documents[1])
    selected = set()
    tokens = set()
    for name in set(changed):
        path = Path(name)
        # Make's page-list interface is whitespace separated.
        if not re.fullmatch(r"[A-Za-z0-9_/+@.\-]+", name):
            return None
        if path.suffix in PAGES:
            selected.add(name)
            tokens.update((name, path.name))
            if name not in documents[0] or name not in documents[1]:
                # Creation/deletion/rename may change any listing or navigation.
                return None
        elif path.name == "evidence.yml" or path.suffix == ".bib":
            try:
                old, new = (_entries(root / name) for root in (before, after))
            except (OSError, ValueError, yaml.YAMLError):
                return None
            keys = {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)}
            if not keys:
                return None
            if any(
                not any(
                    str(key) in text for docs in documents for text in docs.values()
                )
                for key in keys
            ):
                return None
            tokens.update(str(key) for key in keys)
        elif path.suffix in ASSETS:
            if not any(
                name in text or path.name in text
                for docs in documents
                for text in docs.values()
            ):
                return None
            tokens.update((name, path.name))
        else:
            return None
    # Follow includes in both revisions, including ordinary non-underscore files.
    # Basename matching also handles ../ paths; false positives cost only time.
    while True:
        added = {
            name
            for docs in documents
            for name, text in docs.items()
            if any(token in text for token in tokens)
        } - selected
        if not added:
            break
        selected.update(added)
        for name in added:
            tokens.update((name, Path(name).name))
    if not selected:
        return None
    # Includes starting with '_' aren't standalone pages. Quarto's after-side
    # inspect provides the authoritative render set after the builds.
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
    """Prove a paper unaffected, or build it. Dynamic TeX stays conservative."""
    root = (project / directory).resolve()
    if any((project / name).resolve().is_relative_to(root) for name in changed):
        return True
    if any((root / name).exists() for name in ("latexmkrc", ".latexmkrc")):
        return True
    pending = [root / main]
    seen = set()
    dependencies = set()
    pattern = re.compile(
        r"\\(input|include|bibliography|addbibresource|includegraphics)\s*(?:\[[^\]]*\]\s*)?\{([^{}]+)\}"
    )
    while pending:
        source = pending.pop()
        if source in seen:
            continue
        seen.add(source)
        try:
            text = source.read_text()
        except (OSError, UnicodeError):
            return True
        if re.search(
            r"\\(?:openin|read|directlua|lstinputlisting|verbatiminput|includepdf|graphicspath)\b",
            text,
        ):
            return True
        if re.search(r"\\(?:input|include)\s+[^\s{]", text):
            return True
        for command, argument in pattern.findall(text):
            # Macro-generated dependencies cannot be resolved without TeX.
            if any(character in argument for character in "\\#$"):
                return True
            for value in argument.split(","):
                path = (source.parent / value.strip()).resolve()
                dependencies.add(path)
                # TeX engines often resolve nested inputs from the main-file
                # directory; accept either interpretation, never miss one.
                alternate = (root / value.strip()).resolve()
                dependencies.add(alternate)
                if not alternate.suffix:
                    dependencies.add(alternate.with_suffix(".tex"))
                    dependencies.add(alternate.with_suffix(".bib"))
                if source.parent != root and command in {"input", "include"}:
                    return True
                if command in {"input", "include"}:
                    path = path if path.suffix else path.with_suffix(".tex")
                    dependencies.add(path)
                    pending.append(path)
                elif command in {"bibliography", "addbibresource"}:
                    dependencies.add(path if path.suffix else path.with_suffix(".bib"))
    for name in changed:
        path = (project / name).resolve()
        if path in dependencies or any(
            path.with_suffix("") == dep for dep in dependencies
        ):
            return True
        # Build tooling and unknown inputs may generate paper dependencies.
        if path.suffix not in PAGES | ASSETS | {".bib", ".yml", ".yaml"}:
            return True
    return False
