"""Real renderer checks; missing tools fail this suite."""

import json
import shutil
import subprocess

import pytest

from tests.workspace.test_workspace_paper_scaffold import ASSETS


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
    shutil.copytree(ASSETS / "_extensions", tmp_path / "_extensions")
    subprocess.run(
        ["python3", str(ASSETS / "paper-viewer.py")],
        cwd=tmp_path,
        input=json.dumps({"papers": [paper_dir]}),
        text=True,
        check=True,
        capture_output=True,
    )
    render = subprocess.run(
        ["quarto", "render"], cwd=tmp_path, capture_output=True, text=True
    )
    assert render.returncode == 0, render.stdout + render.stderr
    assert (tmp_path / f"_site/{paper_dir}/html/index.html").is_file()
    subprocess.run(["git", "diff", "--exit-code"], cwd=tmp_path, check=True)
    assert not subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=tmp_path
    ).strip()


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


@pytest.mark.parametrize("local_bibliography", [False, True])
def test_overleaf_named_main_requires_its_own_bibliography(
    tmp_path, local_bibliography
):
    paper = tmp_path / "paper"
    paper.mkdir()
    record = paper.parent / ".asta/overleaf" / f"{paper.name}.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("{}")
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
        # latexmk -f may return success despite an unresolved citation. Check
        # the bibliography isolation directly, independent of its exit policy.
        assert "references.bib" in result.stdout + result.stderr
        bbl = paper / "build/conference.bbl"
        assert not bbl.exists() or "Bibliography test" not in bbl.read_text()
