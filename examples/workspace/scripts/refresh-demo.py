"""Keep the example workspace's edited-paper demonstration reproducible."""

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
PAPERS = ("paper",)
# What a pull request's preview calls its comparison, as the shared workflow
# passes it to what-changed.py's --mark, so that the demo reads as that
# preview does.
PREVIEW_LABEL = "in this pull request"


def workflow_ref() -> str:
    """The asta-plugins ref the demo is built from: the release tag, else HEAD."""
    ref = os.environ.get("ASTA_EXAMPLE_REF")
    if ref:
        return ref
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ("href", "src") and value:
                self.add_path(value)
            elif key == "srcset" and value:
                for candidate in value.split(","):
                    if candidate.strip():
                        self.add_path(candidate.strip().split()[0])

    def add_path(self, value):
        url = urlsplit(value)
        if not url.scheme and not url.netloc and url.path:
            self.paths.append(unquote(url.path))


def check(snapshot: Path) -> None:
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if manifest["asta_plugins_ref"] != workflow_ref():
        raise ValueError("demo snapshot uses another asta-plugins ref; refresh it")
    report = snapshot / "what-changed.html"
    page = report.read_text(encoding="utf-8")
    if '<section class="page-diff changed" id="p-lit-review-index-html">' not in page:
        raise ValueError("demo has no edited Quarto page")
    if (
        len(re.findall(r"<ins[\s>]", page)) < 3
        or len(re.findall(r"<del[\s>]", page)) < 3
    ):
        raise ValueError("demo has too few highlighted text edits")
    for paper in PAPERS:
        directory = snapshot / "paper-previews" / paper
        preview = json.loads((directory / "preview.json").read_text(encoding="utf-8"))
        if not preview.get("diff") or not (directory / "what-changed.pdf").is_file():
            raise ValueError(f"demo has no PDF diff for {paper}")
    links = Links()
    links.feed(page)
    root = snapshot.resolve()
    for name in links.paths:
        if name.startswith("/"):
            raise ValueError(f"demo report links outside snapshot: {name}")
        target = (root / name).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"demo report links outside snapshot: {name}")
        if not target.is_file() and not (target / "index.html").is_file():
            raise ValueError(f"demo report links to a missing file: {name}")
    # As in a pull request's preview, the edited page shows its changes in place.
    changes = json.loads(
        (snapshot / "_changes/c0/manifest.json").read_text(encoding="utf-8")
    )
    if not changes.get("pages", {}).get("lit-review/index.html", {}).get("marks"):
        raise ValueError("demo's edited page shows no changes in place")


def copy_site(source: Path, target: Path) -> None:
    # A previous demo, at demo/, isn't part of either site.
    shutil.copytree(
        source,
        target,
        ignore=lambda path, names: (
            [name for name in names if name == ".nojekyll"]
            + (["demo"] if Path(path) == source else [])
        ),
    )


def build(args) -> None:
    if args.baseline_commit == args.changed_commit:
        raise ValueError("demo needs distinct baseline and edited commits")
    old = args.old.resolve()
    new = args.new.resolve()
    generator = args.generator.resolve()
    if not all(
        path.is_file() for path in (old / "index.html", new / "index.html", generator)
    ):
        raise ValueError("both rendered sites and the shared generator are required")
    snapshot = args.output.resolve()
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    # Keep staging outside the inputs so the diff cannot discover its own output.
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        # Exclude prior demos from both inputs, including on repeated local builds.
        before, after = directory / "before", directory / "after"
        copy_site(old, before)
        copy_site(new, after)
        staged = Path(directory) / "preview"
        shutil.copytree(after, staged)
        # What a pull request's preview runs after its build: What changed,
        # with each page's changes marked in place.
        subprocess.run(
            [
                "python3",
                str(generator),
                "--old",
                str(before),
                "--new",
                str(staged),
                "--out",
                str(staged / "what-changed.html"),
                "--title",
                "Workspace demo",
                "--mark",
                PREVIEW_LABEL,
                "--on",
            ],
            check=True,
        )
        (staged / "manifest.json").write_text(
            json.dumps(
                {
                    "asta_plugins_ref": args.ref,
                    "baseline_commit": args.baseline_commit,
                    "changed_commit": args.changed_commit,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        check(staged)
        backup = snapshot.with_name(f".demo-backup-{uuid4().hex}")
        if snapshot.exists():
            snapshot.rename(backup)
        try:
            shutil.copytree(staged, snapshot)
        except OSError:
            if snapshot.exists():
                shutil.rmtree(snapshot)
            if backup.exists():
                backup.rename(snapshot)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    print(f"refreshed {snapshot}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    builder = sub.add_parser("build")
    builder.add_argument("--output", type=Path, required=True)
    builder.add_argument("--old", type=Path, required=True)
    builder.add_argument("--new", type=Path, required=True)
    builder.add_argument("--generator", type=Path, required=True)
    builder.add_argument("--ref", required=True)
    builder.add_argument("--baseline-commit", required=True)
    builder.add_argument("--changed-commit", required=True)
    checker = sub.add_parser("check")
    checker.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        check(args.path)
        print(f"checked {args.path}")


if __name__ == "__main__":
    main()
