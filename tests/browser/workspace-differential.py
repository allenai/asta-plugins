"""Real stateless renders: selected runs must equal --full from the same edit.

Instrumentation wraps the real render entry point and audits real subprocesses;
no renderer, selector, paper builder or comparator is mocked.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from click.testing import CliRunner
from report_signature import report_signature

ROOT = Path(__file__).resolve().parents[2]
DECK = "slides/attention/slides.qmd"
LOOK = "asta-what-changed-look.qmd"
# Only committed source pages: paper/slides index.qmd files are generated,
# ignored build outputs and are absent in the fresh differential clone.
ALL = {
    "index.qmd",
    "appearance.qmd",
    "lit-review/index.qmd",
    DECK,
}


def edit(project, case):
    def replace(name, old, new):
        path = project / name
        text = path.read_text()
        assert old in text, (name, old)
        path.write_text(text.replace(old, new, 1))

    if case == "prose":
        replace("lit-review/index.qmd", "## ", "## Revised ")
        return {"lit-review/index.qmd"}, False
    if case == "metadata":
        replace("lit-review/index.qmd", 'title: "', 'title: "Revised ')
        return ALL, False
    if case == "slide":
        replace(DECK, "## ", "## Revised ")
        return {DECK, LOOK}, False
    if case == "quote":
        replace("evidence.yml", "We propose", "We introduce")
        return {"lit-review/index.qmd"}, False
    if case == "bibliography":
        replace(
            "references.bib",
            "Attention Is All You Need",
            "Attention Is All You Need Revised",
        )
        return {"lit-review/index.qmd"}, True
    if case == "paper-bibliography":
        replace(
            "paper/references.bib",
            "Attention Is All You Need",
            "Attention Is All You Need Revised",
        )
        return {"lit-review/index.qmd"}, True
    if case == "paper":
        replace(
            "paper/main.tex", "\\begin{document}", "\\begin{document}\nA revised paper."
        )
        return ALL, True
    if case == "config":
        replace(
            "_quarto.yml",
            'title: "Asta workspace example"',
            'title: "Revised workspace example"',
        )
        return ALL, False
    if case == "image":
        replace("differential.svg", "#008080", "#800080")
        return {"appearance.qmd"}, False
    if case == "include":
        replace("_sharing.qmd", "Every page", "Each page")
        return {"appearance.qmd"}, False
    config = project / "_quarto.yml"
    value = yaml.safe_load(config.read_text())
    if case == "new":
        (project / "new-page.qmd").write_text("---\ntitle: New page\n---\nNew prose.\n")
        value["project"]["render"].append("new-page.qmd")
        expected = ALL | {"new-page.qmd"}
    elif case == "deleted":
        (project / "appearance.qmd").unlink()
        value["project"]["render"].remove("appearance.qmd")
        expected = ALL - {"appearance.qmd"}
    elif case == "renamed":
        (project / "appearance.qmd").rename(project / "renamed.qmd")
        value["project"]["render"].remove("appearance.qmd")
        value["project"]["render"].append("renamed.qmd")
        expected = ALL - {"appearance.qmd"} | {"renamed.qmd"}
    else:
        raise AssertionError(case)
    config.write_text(yaml.safe_dump(value, sort_keys=False))
    return expected, False


def worker(project, full, record):
    from asta.commands import workspace as module

    renders, commands, copies = [], [], []
    original = module.render_site

    def render(directory, label, pages=None):
        actual = pages
        if actual is None:
            inputs = module._comparison_inputs(directory)
            assert inputs is not None, "Quarto must list full-render inputs"
            actual = sorted(p.relative_to(directory).as_posix() for p in inputs)
        renders.append(
            {
                "side": "after" if label == "the working tree" else "before",
                "pages": actual,
            }
        )
        return original(directory, label, pages)

    def audit(event, args):
        if event == "shutil.copyfile":
            source = Path(args[0]).absolute()
            if source.is_relative_to(project):
                copies.append(source.relative_to(project).as_posix())
        if event == "subprocess.Popen":
            commands.append([str(arg) for arg in args[1]])

    module.render_site = render
    sys.addaudithook(audit)
    result = CliRunner().invoke(
        module.what_changed,
        ["HEAD", "--project", str(project), "--timings", *(["--full"] if full else [])],
    )
    print(result.output, flush=True)
    record.write_text(
        json.dumps(
            {"renders": renders, "commands": commands, "copies": copies}, indent=2
        )
    )
    if result.exception:
        raise result.exception


def check(artifacts):
    artifacts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="asta-differential-") as temp:
        clone = Path(temp) / "repo"
        subprocess.run(["git", "clone", "--shared", str(ROOT), str(clone)], check=True)
        project = clone / "examples/workspace"
        # One deterministic asset, referenced by an ordinary project page.
        (project / "differential.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="#008080"/></svg>'
        )
        with (project / "appearance.qmd").open("a") as stream:
            stream.write("\n![Differential asset](differential.svg)\n")
        subprocess.run(
            [
                "git",
                "add",
                "examples/workspace/appearance.qmd",
                "examples/workspace/differential.svg",
            ],
            cwd=clone,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Example check",
                "-c",
                "user.email=example@localhost",
                "commit",
                "-m",
                "Prepare differential asset",
            ],
            cwd=clone,
            check=True,
        )
        # Reuse the cold build's managed rules and extensions, verified against
        # this commit: a clone has none, and `sync` alone fetches no extensions.
        from asta.commands.workspace import copy_ignored_render_inputs

        copy_ignored_render_inputs(ROOT / "examples/workspace", project)
        for required in (
            ".asta/cache/workspace.mk",
            "_extensions/evidence/snippet.lua",
            "_extensions/asta-theme/light.scss",
        ):
            assert (project / required).is_file(), f"bootstrap missed {required}"
        for case in (
            "prose",
            "metadata",
            "slide",
            "quote",
            "bibliography",
            "config",
            "image",
            "new",
            "deleted",
            "renamed",
            "paper-bibliography",
            "paper",
            "include",
        ):
            subprocess.run(["git", "restore", "."], cwd=clone, check=True)
            for name in ("new-page.qmd", "renamed.qmd"):
                (project / name).unlink(missing_ok=True)
            expected, paper = edit(project, case)
            signatures = []
            for full in (False, True):
                name = f"{case}-{'full' if full else 'selected'}"
                record = artifacts / f"{name}.json"
                run = subprocess.run(
                    [
                        sys.executable,
                        __file__,
                        "--worker",
                        str(project),
                        str(int(full)),
                        str(record),
                    ],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                (artifacts / f"{name}.log").write_text(run.stdout)
                print(f"\n### {name}\n{run.stdout}", flush=True)
                assert run.returncode == 0, name
                data = json.loads(record.read_text())
                assert len(data["renders"]) == 2, data
                if not full:
                    for render in data["renders"]:
                        wanted = expected
                        if case == "new" and render["side"] == "before":
                            wanted = ALL
                        elif (
                            case in ("deleted", "renamed")
                            and render["side"] == "before"
                        ):
                            wanted = ALL
                        actual = render["pages"]
                        assert set(actual) == wanted, (name, render, wanted)
                    built = any(
                        any("paper-preview.sh" in arg for arg in cmd)
                        for cmd in data["commands"]
                    )
                    assert built == paper, (name, "paper build", built)
                changed = set(
                    subprocess.check_output(
                        [
                            "git",
                            "diff",
                            "--name-only",
                            "HEAD",
                            "--",
                            "examples/workspace",
                        ],
                        cwd=clone,
                        text=True,
                    ).splitlines()
                )
                changed |= set(
                    subprocess.check_output(
                        [
                            "git",
                            "ls-files",
                            "--others",
                            "--exclude-standard",
                            "examples/workspace",
                        ],
                        cwd=clone,
                        text=True,
                    ).splitlines()
                )
                for copied in data["copies"]:
                    assert not any(
                        part.startswith(".env") for part in Path(copied).parts
                    ), copied
                    assert (
                        copied.startswith((".asta/cache/", "_extensions/"))
                        or "examples/workspace/" + copied in changed
                    ), (name, "unchanged file copied", copied)
                assert not any(
                    any(word in arg.lower() for word in ("playwright", "chromium"))
                    for cmd in data["commands"]
                    for arg in cmd
                ), name
                signatures.append(
                    report_signature(project / ".asta/cache/what-changed")
                )
            assert signatures[0] == signatures[1], (
                f"{case}: selected pages/marked words differ from same-run --full"
            )


if __name__ == "__main__":
    if sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]), bool(int(sys.argv[3])), Path(sys.argv[4]))
    else:
        check(Path(sys.argv[1]).resolve())
