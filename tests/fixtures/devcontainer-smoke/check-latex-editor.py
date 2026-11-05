"""Compile with the recipe shipped to VS Code by the image."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

metadata = json.loads(os.environ["ASTA_EDITOR_METADATA"])
settings = next(
    (
        item["customizations"]["vscode"]["settings"]
        for item in metadata
        if "settings" in item.get("customizations", {}).get("vscode", {})
    ),
    None,
)
if settings is None:
    raise SystemExit("Image metadata is missing LaTeX Workshop settings")
recipe = settings["latex-workshop.latex.recipes"][0]
tool = next(
    (
        tool
        for tool in settings["latex-workshop.latex.tools"]
        if tool["name"] == recipe["tools"][0]
    ),
    None,
)
if tool is None:
    raise SystemExit(f"Image metadata is missing tool {recipe['tools'][0]}")


def compile_paper(paper: Path) -> Path:
    outdir = Path(settings["latex-workshop.latex.outDir"].replace("%DIR%", str(paper)))
    if not outdir.is_absolute():
        outdir = paper / outdir
    args = [
        arg.replace("%OUTDIR%", str(outdir)).replace("%DOC%", str(paper / "main"))
        for arg in tool["args"]
    ]
    subprocess.run([tool["command"], *args], cwd=paper, check=True)
    return outdir


def require_output(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"Editor recipe did not produce a nonempty {path}")


paper = Path.cwd()
outdir = compile_paper(paper)
require_output(outdir / "main.pdf")
require_output(outdir / "main.synctex.gz")

# A paper's engine choice must survive the image's default recipe.
with tempfile.TemporaryDirectory() as directory:
    alternate = Path(directory) / "paper"
    shutil.copytree(
        paper, alternate, ignore=shutil.ignore_patterns(outdir.name, "latexmkrc")
    )
    (alternate / "latexmkrc").write_text("$pdf_mode = 5;\n")
    alternate_outdir = compile_paper(alternate)
    require_output(alternate_outdir / "main.pdf")
    require_output(alternate_outdir / "main.synctex.gz")
    log = (alternate_outdir / "main.log").read_text()
    if "XeTeX" not in log:
        raise SystemExit("The editor recipe overrode latexmkrc's engine")

    shutil.rmtree(alternate_outdir)
    (alternate / "latexmkrc").write_text("$pdf_mode = 0;\n")
    alternate_outdir = compile_paper(alternate)
    require_output(alternate_outdir / "main.dvi")
    require_output(alternate_outdir / "main.synctex.gz")
    if (alternate_outdir / "main.pdf").exists():
        raise SystemExit("The editor recipe overrode latexmkrc's DVI-only output")
