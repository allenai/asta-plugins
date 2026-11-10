"""The reusable paper starter builds with the project's bibliography and engine."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = (
    Path(__file__).resolve().parents[2] / "plugins/asta-tools/skills/workspace/assets"
)


@pytest.mark.parametrize(
    "main_name", ["main.tex", "conference draft.tex", "-pv.tex", ".draft.tex"]
)
@pytest.mark.parametrize(
    "declaration",
    [
        r"\documentclass [draft]{article}",
        "\\documentclass\n% class choice\n [draft]{article}",
        r"\newcommand{\percent}{\%}\documentclass{article}",
        r"\\\% \documentclass{article}",
    ],
)
def test_paper_targets_select_directory_and_preserve_engine(
    tmp_path, main_name, declaration
):
    paper = tmp_path / "papers/custom name"
    paper.mkdir(parents=True)
    (paper / main_name).write_text(declaration)
    (paper / "lookalike.tex").write_text(r"\documentclassfoo{article}")
    (paper / "escaped.tex").write_text(r"\\documentclass{not_a_declaration}")
    for count in (2, 4):
        (paper / f"comment-{count}.tex").write_text(
            "\\" * count + r"% \documentclass{commented}"
        )
    (paper / "linked.tex").symlink_to(main_name)
    if main_name != "main.tex":
        (paper / "main.tex").symlink_to("missing")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tool = bin_dir / "latexmk"
    tool.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['CALL']).write_text(json.dumps([os.getcwd(), sys.argv[1:]]))\n"
    )
    tool.chmod(0o755)
    call = tmp_path / "call.json"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "CALL": str(call)}
    for target, expected in [("paper", "-synctex=1"), ("paper-clean", "-C")]:
        result = subprocess.run(
            [
                "make",
                "-f",
                str(ASSETS / "workspace.mk"),
                target,
                "PAPER_DIR=papers/custom name",
            ],
            cwd=tmp_path,
            env=env,
            check=True,
            capture_output=True,
        )
        directory, args = json.loads(call.read_text())
        assert directory == str(paper)
        assert expected in args and f"./{main_name}" in args
        assert "-outdir=build" in args
        assert "-pdf" not in args and "-xelatex" not in args
        assert "latexmk " in result.stdout.decode()
        assert f'"./{main_name}"' in result.stdout.decode()


def test_paper_target_reports_missing_source(tmp_path):
    result = subprocess.run(
        ["make", "-f", str(ASSETS / "workspace.mk"), "paper"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "No paper directory paper" in result.stderr
    assert "latexmk" not in result.stderr


@pytest.mark.parametrize("target", ["paper", "paper-clean"])
@pytest.mark.parametrize("failure", ["missing-directory", "no-main", "ambiguous"])
def test_failed_main_selection_never_invokes_latexmk(tmp_path, target, failure):
    paper = tmp_path / "paper"
    if failure != "missing-directory":
        paper.mkdir()
        (paper / "section.tex").write_text(r"% \documentclass{commented}")
        if failure == "ambiguous":
            for name in ("a.tex", "b.tex"):
                (paper / name).write_text(r"\documentclass{article}")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tool = bin_dir / "latexmk"
    tool.write_text("#!/bin/sh\ntouch latexmk-was-invoked\n")
    tool.chmod(0o755)
    result = subprocess.run(
        ["make", "-f", str(ASSETS / "workspace.mk"), target],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        capture_output=True,
    )

    assert result.returncode != 0
    assert not list(tmp_path.rglob("latexmk-was-invoked"))


@pytest.mark.parametrize("paper_dir", ["paper", "papers/a", "papers/custom name"])
def test_bibliography_rc_supports_string_evaluation(tmp_path, paper_dir):
    paper = tmp_path / paper_dir
    paper.mkdir(parents=True)
    (tmp_path / ".git").mkdir()
    (tmp_path / "references.bib").write_text("")
    shutil.copy(ASSETS / "paper/latexmkrc", paper / "latexmkrc")
    result = subprocess.check_output(
        [
            "perl",
            "-e",
            "$search_path_separator = ':'; "
            "open my $rc, '<', 'latexmkrc' or die $!; "
            "eval do { local $/; <$rc> }; die $@ if $@; "
            "print $ENV{'BIBINPUTS'};",
        ],
        cwd=paper,
        env={**os.environ, "BIBINPUTS": "existing"},
        text=True,
    )
    assert result == f"{tmp_path}:existing:"


@pytest.mark.parametrize(
    "paper_dir", ["paper", "papers/imported", "papers/custom name"]
)
@pytest.mark.parametrize("git_marker", ["directory", "file", "absent"])
def test_overleaf_bibliography_rc_stays_inside_paper(tmp_path, paper_dir, git_marker):
    paper = tmp_path / paper_dir
    paper.mkdir(parents=True)
    (tmp_path / "references.bib").write_text("Root bibliography")
    if git_marker == "directory":
        (tmp_path / ".git").mkdir()
    elif git_marker == "file":
        (tmp_path / ".git").write_text("gitdir: elsewhere\n")
    record = tmp_path / ".asta/overleaf" / f"{paper_dir}.json"
    record.parent.mkdir(parents=True)
    record.write_text("{}")
    shutil.copy(ASSETS / "paper/latexmkrc", paper / "latexmkrc")
    result = subprocess.check_output(
        [
            "perl",
            "-e",
            "$search_path_separator = ':'; do './latexmkrc' or die $@; "
            "print $ENV{'BIBINPUTS'};",
        ],
        cwd=paper,
        env={**os.environ, "BIBINPUTS": "existing"},
        text=True,
    )

    assert result == f"{paper}:existing:"


@pytest.mark.parametrize("git_marker", ["directory", "file"])
def test_bibliography_rc_ignores_pairing_outside_checkout(tmp_path, git_marker):
    workspace = tmp_path / "workspace"
    paper = workspace / "paper"
    paper.mkdir(parents=True)
    (workspace / "references.bib").write_text("Workspace bibliography")
    if git_marker == "directory":
        (workspace / ".git").mkdir()
    else:
        (workspace / ".git").write_text("gitdir: elsewhere\n")
    record = tmp_path / ".asta/overleaf/workspace/paper.json"
    record.parent.mkdir(parents=True)
    record.write_text("{}")
    shutil.copy(ASSETS / "paper/latexmkrc", paper / "latexmkrc")
    result = subprocess.check_output(
        [
            "perl",
            "-e",
            "$search_path_separator = ':'; do './latexmkrc' or die $@; "
            "print $ENV{'BIBINPUTS'};",
        ],
        cwd=paper,
        env={**os.environ, "BIBINPUTS": "existing"},
        text=True,
    )

    assert result == f"{workspace}:existing:"


@pytest.mark.parametrize("paper_dir", ["paper", "papers/a", "papers/custom name"])
def test_paper_ignore_entries_keep_sources(tmp_path, paper_dir):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(
        (ASSETS / "paper/gitignore").read_text().replace("{{PAPER_DIR}}", paper_dir)
    )
    outputs = [
        "build/main.pdf",
        "build/main.bbl",
        "main.fls",
        "main.fdb_latexmk",
        "main.synctex.gz",
        "what-changed.tex",
        "html/index.qmd",
        "html/paper-viewer.js",
    ]
    for name in outputs:
        path = f"{paper_dir}/{name}"
        result = subprocess.run(
            ["git", "check-ignore", path], cwd=tmp_path, capture_output=True
        )
        assert result.returncode == 0, path
    for path in [f"{paper_dir}/main.tex", f"{paper_dir}/latexmkrc", "references.bib"]:
        result = subprocess.run(
            ["git", "check-ignore", path], cwd=tmp_path, capture_output=True
        )
        assert result.returncode == 1, path
