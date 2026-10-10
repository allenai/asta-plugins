"""The reusable paper starter builds with the project's bibliography and engine."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = (
    Path(__file__).resolve().parents[1] / "plugins/asta-tools/skills/workspace/assets"
)


@pytest.mark.skipif(not shutil.which("quarto"), reason="requires Quarto")
@pytest.mark.parametrize("paper_dir", ["paper", "papers/a"])
def test_first_viewer_render_keeps_scaffold_clean(tmp_path, paper_dir):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    config = (ASSETS / "_quarto.yml").read_text().replace("{{TITLE}}", "Starter")
    config = config.replace("{{REPO_URL}}", "https://github.com/allenai/asta-plugins")
    config = config.replace(
        "  type: website",
        f"  type: website\n  render:\n    - index.qmd\n    - {paper_dir}/html/index.qmd",
    )
    (tmp_path / "_quarto.yml").write_text(config)
    (tmp_path / "index.qmd").write_text("---\ntitle: Starter\n---\n")
    (tmp_path / "references.bib").write_text("")
    shutil.copy(ASSETS / "evidence.yml", tmp_path / "evidence.yml")
    (tmp_path / ".gitignore").write_text(
        (ASSETS / "gitignore").read_text()
        + (ASSETS / "paper/gitignore").read_text().replace("{{PAPER_DIR}}", paper_dir)
    )
    subprocess.run(
        [
            "git",
            "add",
            ".gitignore",
            "_quarto.yml",
            "index.qmd",
            "references.bib",
            "evidence.yml",
        ],
        cwd=tmp_path,
        check=True,
    )
    shutil.copytree(ASSETS / "_extensions/evidence", tmp_path / "_extensions/evidence")
    subprocess.run(
        ["python3", str(ASSETS / "paper-viewer.py")],
        cwd=tmp_path,
        input=json.dumps({"papers": [paper_dir]}),
        text=True,
        check=True,
        capture_output=True,
    )
    subprocess.run(["quarto", "render"], cwd=tmp_path, check=True, capture_output=True)
    assert (tmp_path / f"_site/{paper_dir}/html/index.html").is_file()
    subprocess.run(["git", "diff", "--exit-code"], cwd=tmp_path, check=True)
    assert not subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=tmp_path
    ).strip()


@pytest.mark.skipif(not shutil.which("make"), reason="requires make")
@pytest.mark.parametrize("main_name", ["main.tex", "conference draft.tex"])
def test_paper_targets_select_directory_and_preserve_engine(tmp_path, main_name):
    paper = tmp_path / "papers/custom name"
    paper.mkdir(parents=True)
    (paper / main_name).write_text(r"\documentclass [draft]{article}")
    (paper / "lookalike.tex").write_text(r"\documentclassfoo{article}")
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
        assert expected in args and main_name in args
        assert "-outdir=build" in args
        assert "-pdf" not in args and "-xelatex" not in args
        assert "latexmk " in result.stdout.decode()
        assert f'"{main_name}"' in result.stdout.decode()


@pytest.mark.skipif(not shutil.which("make"), reason="requires make")
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


@pytest.mark.skipif(not shutil.which("make"), reason="requires make")
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


@pytest.mark.skipif(not shutil.which("perl"), reason="requires Perl")
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


@pytest.mark.skipif(not shutil.which("perl"), reason="requires Perl")
def test_overleaf_bibliography_rc_stays_inside_paper(tmp_path):
    paper = tmp_path / "papers/imported"
    paper.mkdir(parents=True)
    (tmp_path / "references.bib").write_text("Root bibliography")
    (paper / "overleaf.json").write_text("{}")
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


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("make", "latexmk", "pdftotext")),
    reason="requires the TeX image",
)
@pytest.mark.parametrize("paper_dir", ["paper", "papers/a", "papers/custom name"])
def test_starter_resolves_shared_bibliography(tmp_path, paper_dir):
    paper = tmp_path / paper_dir
    paper.mkdir(parents=True)
    for name in ("main.tex", "latexmkrc"):
        shutil.copy(ASSETS / "paper" / name, paper / name)
    source = paper / "main.tex"
    source.write_text(
        source.read_text()
        .replace("{{TITLE}}", "Starter")
        .replace("Write the paper here.", r"A cited result \citep{sample}.")
        .replace(r"% \bibliography{references}", r"\bibliography{references}")
    )
    (tmp_path / "references.bib").write_text(
        "@article{sample, author={Example, A.}, title={Shared bibliography test}, "
        "journal={Example Journal}, year={2026}}\n"
    )
    subprocess.run(
        ["make", "-f", str(ASSETS / "workspace.mk"), "paper", f"PAPER_DIR={paper_dir}"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    pdf = paper / "build/main.pdf"
    assert pdf.stat().st_size > 0
    assert "Shared bibliography test" in (paper / "build/main.bbl").read_text()
    text = subprocess.check_output(["pdftotext", str(pdf), "-"], text=True)
    assert "Shared bibliography test" in text and "[?]" not in text


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("make", "latexmk", "pdftotext")),
    reason="requires the TeX image",
)
@pytest.mark.parametrize("local_bibliography", [False, True])
def test_overleaf_named_main_requires_its_own_bibliography(
    tmp_path, local_bibliography
):
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "overleaf.json").write_text("{}")
    shutil.copy(ASSETS / "paper/latexmkrc", paper / "latexmkrc")
    (paper / "conference.tex").write_text(
        r"\documentclass{article}\begin{document}"
        r"A cited result \cite{sample}.\bibliographystyle{plain}"
        r"\bibliography{references}\end{document}"
    )
    bibliography = (
        "@article{sample, author={Example, A.}, title={Bibliography test}, "
        "journal={Example Journal}, year={2026}}\n"
    )
    (tmp_path / "references.bib").write_text(bibliography)
    if local_bibliography:
        (paper / "references.bib").write_text(bibliography)
    result = subprocess.run(
        ["make", "-f", str(ASSETS / "workspace.mk"), "paper"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    if local_bibliography:
        assert result.returncode == 0, result.stdout + result.stderr
        text = subprocess.check_output(
            ["pdftotext", str(paper / "build/conference.pdf"), "-"], text=True
        )
        assert "Bibliography test" in text and "[?]" not in text
    else:
        assert result.returncode != 0
        assert "references.bib" in result.stdout + result.stderr
        bbl = paper / "build/conference.bbl"
        assert not bbl.exists() or "Bibliography test" not in bbl.read_text()
