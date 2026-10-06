"""Compile with the recipe shipped to VS Code by the image."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

metadata = json.loads(os.environ["ASTA_EDITOR_METADATA"])
settings = next(
    item["customizations"]["vscode"]["settings"]
    for item in metadata
    if "settings" in item.get("customizations", {}).get("vscode", {})
)
recipe = settings["latex-workshop.latex.recipes"][0]
tool = next(
    tool
    for tool in settings["latex-workshop.latex.tools"]
    if tool["name"] == recipe["tools"][0]
)


def compile_paper(paper: Path) -> None:
    args = [
        arg.replace("%OUTDIR%", str(paper / "build")).replace(
            "%DOC%", str(paper / "main")
        )
        for arg in tool["args"]
    ]
    subprocess.run([tool["command"], *args], cwd=paper, check=True)


paper = Path.cwd()
compile_paper(paper)

# A paper's engine choice must survive the image's default recipe.
with tempfile.TemporaryDirectory() as directory:
    alternate = Path(directory)
    for name in ("main.tex", "refs.bib"):
        shutil.copyfile(paper / name, alternate / name)
    (alternate / "latexmkrc").write_text("$pdf_mode = 5;\n")
    compile_paper(alternate)
    log = (alternate / "build/main.log").read_text()
    assert "XeTeX" in log, "The editor recipe overrode latexmkrc's engine"
    assert (alternate / "build/main.synctex.gz").stat().st_size > 0
