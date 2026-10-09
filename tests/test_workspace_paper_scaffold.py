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
def test_paper_targets_select_directory_and_preserve_engine(tmp_path):
    paper = tmp_path / "papers/custom name"
    paper.mkdir(parents=True)
    (paper / "main.tex").write_text("Test source")
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
        subprocess.run(
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
        assert expected in args and "main.tex" in args
        assert "-outdir=build" in args
        assert "-pdf" not in args and "-xelatex" not in args


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
