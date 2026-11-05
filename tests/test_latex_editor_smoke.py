"""Exercise the image smoke checker's failures without a TeX installation."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tests/fixtures/devcontainer-smoke/check-latex-editor.py"


@pytest.mark.parametrize("failure", ["", "pdf", "engine", "settings", "tool"])
def test_editor_smoke_checks_survive_optimization(tmp_path, failure):
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(r"\input{extra}")
    (paper / "extra.tex").write_text("Additional paper input")
    compiler = tmp_path / "compiler.py"
    compiler.write_text(
        """
import sys
from pathlib import Path

paper = Path.cwd()
if not (paper / 'extra.tex').is_file():
    raise SystemExit('Paper input was not copied')
outdir = Path(next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('-outdir=')))
outdir.mkdir(parents=True, exist_ok=True)
rc = (paper / 'latexmkrc').read_text() if (paper / 'latexmkrc').exists() else ''
alternate = '$pdf_mode = 5' in rc
dvi = '$pdf_mode = 0' in rc
if not (alternate and sys.argv[1] == 'pdf'):
    (outdir / ('main.dvi' if dvi else 'main.pdf')).write_text('output')
(outdir / 'main.synctex.gz').write_text('synctex')
(outdir / 'main.log').write_text('XeTeX' if alternate and sys.argv[1] != 'engine' else 'pdfTeX')
"""
    )
    label = re.findall(
        r"^LABEL devcontainer\.metadata='(.+)'$",
        (ROOT / "Dockerfile").read_text(),
        re.M,
    )[-1]
    metadata = json.loads(label)
    settings = metadata[-1]["customizations"]["vscode"]["settings"]
    tool = settings["latex-workshop.latex.tools"][0]
    tool["command"] = sys.executable
    tool["args"] = [str(compiler), failure, *tool["args"]]
    settings["latex-workshop.latex.outDir"] = "%DIR%/custom-output"
    if failure == "settings":
        del metadata[-1]["customizations"]["vscode"]["settings"]
    if failure == "tool":
        settings["latex-workshop.latex.tools"] = []
    result = subprocess.run(
        [sys.executable, "-O", str(CHECKER)],
        cwd=paper,
        env={**os.environ, "ASTA_EDITOR_METADATA": json.dumps(metadata)},
        text=True,
        capture_output=True,
    )
    if failure:
        assert result.returncode != 0
        assert {
            "pdf": "main.pdf",
            "engine": "overrode latexmkrc's engine",
            "settings": "missing LaTeX Workshop settings",
            "tool": "missing tool latexmk",
        }[failure] in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert (paper / "custom-output/main.pdf").is_file()
