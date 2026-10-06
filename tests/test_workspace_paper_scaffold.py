"""The reusable paper starter builds with the project's bibliography and engine."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = Path("plugins/asta-tools/skills/workspace/assets").resolve()


@pytest.mark.skipif(not shutil.which("make"), reason="requires make")
def test_paper_targets_select_directory_and_preserve_engine(tmp_path):
    paper = tmp_path / "papers/custom name"
    paper.mkdir(parents=True)
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
        assert "-pdf" not in args and "-xelatex" not in args


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("make", "latexmk", "pdftotext")),
    reason="requires the TeX image",
)
def test_starter_resolves_shared_bibliography(tmp_path):
    paper = tmp_path / "paper"
    shutil.copytree(ASSETS / "paper", paper)
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
        ["make", "-f", str(ASSETS / "workspace.mk"), "paper"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    pdf = paper / "build/main.pdf"
    assert pdf.stat().st_size > 0
    assert "Shared bibliography test" in (paper / "build/main.bbl").read_text()
    text = subprocess.check_output(["pdftotext", str(pdf), "-"], text=True)
    assert "Shared bibliography test" in text and "[?]" not in text
