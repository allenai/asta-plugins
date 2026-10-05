"""Exercise the paper preview's Git and artifact flow with fake TeX commands."""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/asta-tools/skills/workspace/assets/paper-preview.sh"
)


def run(*args, cwd, env=None):
    return subprocess.run(
        args, cwd=cwd, env=env, check=True, capture_output=True, text=True
    )


def paper_repo(tmp_path, old_paper=True):
    repo = tmp_path / "repo"
    repo.mkdir()
    run("git", "init", "-q", cwd=repo)
    run("git", "config", "user.email", "test@example.invalid", cwd=repo)
    run("git", "config", "user.name", "Test", cwd=repo)
    if old_paper:
        (repo / "paper").mkdir()
        (repo / "paper/main.tex").write_text("old")
        run("git", "add", "paper/main.tex", cwd=repo)
        run("git", "commit", "-qm", "base", cwd=repo)
    else:
        run("git", "commit", "--allow-empty", "-qm", "base", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "paper").mkdir(exist_ok=True)
    (repo / "paper/main.tex").write_text("new")
    run("git", "add", "paper/main.tex", cwd=repo)
    run("git", "commit", "-qm", "edit", cwd=repo)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commands = {
        "latexmk": '#!/bin/bash\nmkdir -p build\nname="${@: -1}"\nprintf pdf > "build/${name%.tex}.pdf"\nprintf "%s\\n" "${FAKE_LATEX_LOG:-}" > build/main.log\nif [ -n "${FAKE_BIBTEX_LOG:-}" ]; then printf "%s\\n" "$FAKE_BIBTEX_LOG" > build/main.blg; fi\nif [ -n "${FAKE_BBL:-}" ]; then printf "%s\\n" "$FAKE_BBL" > build/main.bbl; fi\nprintf "PWD %s\\nINPUT main.tex\\n" "$PWD" > build/main.fls\nif [ -n "${FAKE_LATEX_INPUT:-}" ]; then printf "INPUT %s\\n" "$FAKE_LATEX_INPUT" >> build/main.fls; fi\n',
        "latexdiff": "#!/bin/bash\nprintf '\\\\begin{document}\\n\\\\DIFadd{new}\\n'\n",
        "pdftoppm": '#!/bin/bash\nname="${@: -1}"\nprintf png > "${name}-1.png"\n',
        "latexmlc": '#!/bin/bash\nfor arg in "$@"; do case "$arg" in --dest=*) dest=${arg#--dest=};; --log=*) log=${arg#--log=};; esac; done\nprintf "<html><head></head><body><a href=\\"javascript:alert(1)\\">paper</a></body></html>" > "$dest"\nprintf "%s" "${@: -1}" > "$(dirname "$dest")/x1.png"\nprintf "Conversion complete: 0 errors; 0 warnings\\n" > "$log"\n',
    }
    for name, contents in commands.items():
        path = bin_dir / name
        path.write_text(contents)
        path.chmod(0o755)
    with (bin_dir / "latexmk").open("a") as mock:
        mock.write(
            'for arg in "$@"; do case "$arg" in -deps-escape=*) exit 2;; esac; done\n'
        )
        mock.write('printf "%s\\n" "$*" >> latexmk-args.txt\n')
        mock.write(
            'deps_escape="${FAKE_DEPS_ESCAPE:-none}"\n'
            'for arg in "$@"; do\n'
            '  if [[ "$arg" == *\'$deps_escape = "none";\'* ]]; then deps_escape=none; fi\n'
            "done\n"
            "printf '%s' 'build/main.pdf :\\' > build/main.dep\n"
            "printf '\\n    main.tex' >> build/main.dep\n"
            'if [ -n "$FAKE_LATEX_DEPS" ]; then\n'
            "  while IFS= read -r dep; do\n"
            '    case "$deps_escape" in\n'
            '      unix) dep="${dep// /\\\\ }";;\n'
            '      nmake) dep="${dep// /^ }";;\n'
            "    esac\n"
            "    printf '\\\\\\n    %s' \"$dep\" >> build/main.dep\n"
            '  done <<< "$FAKE_LATEX_DEPS"\n'
            "fi\n"
            "printf '\\n' >> build/main.dep\n"
        )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_LATEX_DEPS"] = ""
    return repo, base, env, bin_dir


def test_paper_preview_builds_current_and_diff_pdfs(tmp_path):
    repo, base, env, _ = paper_repo(tmp_path)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert (repo / "_site/paper-previews/paper/what-changed.pdf").exists()
    assert (repo / "_site/paper-previews/paper/html/index.html").exists()
    assert (repo / "_site/paper-previews/paper/html-diff/index.html").exists()
    html = (repo / "_site/paper-previews/paper/html/index.html").read_text()
    assert 'http-equiv="Content-Security-Policy"' in html
    assert "script-src 'none'" in html
    assert html.index("Content-Security-Policy") < html.index('href="javascript:')
    assert (
        repo / "_site/paper-previews/paper/html/x1.png"
    ).read_text() == "paper/main.tex"
    assert (
        "what-changed."
        in (repo / "_site/paper-previews/paper/html-diff/x1.png").read_text()
    )
    assert (repo / "_site/paper-previews/paper/diff-page-1.png").exists()
    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {
        "changed": True,
        "diff": True,
        "html_diff": True,
        "other_inputs": False,
        "thumbnail_limit": 12,
    }
    assert not list((repo / "paper").glob("what-changed.*.tex"))
    commands = (repo / "paper/latexmk-args.txt").read_text().splitlines()
    assert len(commands) == 2
    assert all("-pdf" not in command for command in commands)
    assert all("$pdf_mode ||= 1;" in command for command in commands)
    assert '$deps_escape = "none";' in commands[0]


def test_quarto_pdf_only_packages_are_omitted_from_html_conversion(tmp_path):
    repo, _, env, bin_dir = paper_repo(tmp_path)
    source = repo / "paper/main.tex"
    original = (
        r"\usepackage{bookmark}"
        "\n"
        r"\IfFileExists{footnotehyper.sty}{\usepackage{footnotehyper}}{\usepackage{footnote}}"
        "\n"
        r"\makesavenoteenv{longtable}"
        "\n"
        r"pdfcreator={LaTeX via pandoc}"
        "\n"
    )
    source.write_text(original)
    capture = repo / "html-input.tex"
    capture_bbl = repo / "html-input-bbl.txt"
    (repo / "paper/build").mkdir()
    (repo / "paper/build/main.bbl").write_text("compiled bibliography")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with (bin_dir / "latexmlc").open("a") as mock:
        mock.write('cp "${@: -1}" "$FAKE_CAPTURE"\n')
        mock.write('cat "$(dirname "${@: -1}")/main.bbl" > "$FAKE_CAPTURE_BBL"\n')
    env["FAKE_CAPTURE"] = str(capture)
    env["FAKE_CAPTURE_BBL"] = str(capture_bbl)
    env["TMPDIR"] = str(scratch)

    run("bash", str(SCRIPT), "", cwd=repo, env=env)

    converted = capture.read_text()
    assert "bookmark" not in converted
    assert r"\usepackage{hyperref}" in converted
    assert "footnotehyper" not in converted
    assert "makesavenoteenv" not in converted
    assert "pdfcreator={LaTeX via pandoc}" in converted
    assert capture_bbl.read_text() == "compiled bibliography"
    assert source.read_text() == original
    assert (
        (repo / "_site/paper-previews/paper/html/x1.png")
        .read_text()
        .endswith("/main.tex")
    )
    assert not list(scratch.iterdir())


def test_non_quarto_paper_passes_original_source_to_latexml(tmp_path):
    repo, _, env, bin_dir = paper_repo(tmp_path)
    source = repo / "paper/main.tex"
    capture = repo / "html-input.tex"
    with (bin_dir / "latexmlc").open("a") as mock:
        mock.write('cp "${@: -1}" "$FAKE_CAPTURE"\n')
    env["FAKE_CAPTURE"] = str(capture)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env["TMPDIR"] = str(scratch)

    run("bash", str(SCRIPT), "", cwd=repo, env=env)

    assert capture.read_text() == source.read_text()
    assert (repo / "_site/paper-previews/paper/html/x1.png").read_text() == (
        "paper/main.tex"
    )
    assert not list(scratch.iterdir())


def test_quarto_preparation_failure_falls_back_to_original_source(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    source = repo / "paper/main.tex"
    original = b"pdfcreator={LaTeX via pandoc}\ninvalid utf-8: \xff\n"
    source.write_bytes(original)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env["TMPDIR"] = str(scratch)

    result = run("bash", str(SCRIPT), "", cwd=repo, env=env)

    assert "Could not prepare Quarto TeX" in result.stdout
    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert (repo / "_site/paper-previews/paper/html/x1.png").read_text() == (
        "paper/main.tex"
    )
    assert source.read_bytes() == original
    assert not list(scratch.iterdir())


def test_temp_directory_failure_falls_back_to_original_source(tmp_path):
    repo, _, env, bin_dir = paper_repo(tmp_path)
    (repo / "paper/main.tex").write_text("pdfcreator={LaTeX via pandoc}\n")
    (bin_dir / "mktemp").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "mktemp").chmod(0o755)

    result = run("bash", str(SCRIPT), "", cwd=repo, env=env)

    assert "Could not create a temporary TeX directory" in result.stdout
    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert (repo / "_site/paper-previews/paper/html/x1.png").read_text() == (
        "paper/main.tex"
    )


def test_paper_preview_builds_second_paper_in_its_own_directory(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    second = repo / "latex"
    second.mkdir()
    (second / "main.tex").write_text("old")
    (second / "latexmkrc").write_text("$pdf_mode = 1;\n")
    run("git", "add", "latex/main.tex", "latex/latexmkrc", cwd=repo)
    run("git", "commit", "-qm", "add second paper", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (second / "main.tex").write_text("new")
    run("git", "commit", "-qam", "edit second paper", cwd=repo)

    run("bash", str(SCRIPT), base, "latex", cwd=repo, env=env)

    assert (repo / "_site/paper-previews/latex/main.pdf").exists()
    assert (repo / "_site/paper-previews/latex/what-changed.pdf").exists()
    assert (repo / "_site/paper-previews/latex/html/index.html").exists()
    assert (repo / "_site/paper-previews/latex/html-diff/index.html").exists()
    assert (repo / "_site/paper-previews/latex/preview.json").exists()
    assert not (repo / "_site/paper-previews/paper/main.pdf").exists()


def test_nested_paper_builds_pdf_and_diff(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    nested = repo / "lit-review/latex"
    nested.mkdir(parents=True)
    (nested / "main.tex").write_text("old")
    (nested / "latexmkrc").write_text("$pdf_mode = 1;\n")
    run(
        "git",
        "add",
        "lit-review/latex/main.tex",
        "lit-review/latex/latexmkrc",
        cwd=repo,
    )
    run("git", "commit", "-qm", "add nested paper", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (nested / "main.tex").write_text("new")
    run("git", "commit", "-qam", "edit nested paper", cwd=repo)

    run("bash", str(SCRIPT), base, "lit-review/latex", cwd=repo, env=env)

    assert (repo / "_site/paper-previews/lit-review/latex/main.pdf").exists()
    assert (repo / "_site/paper-previews/lit-review/latex/what-changed.pdf").exists()
    assert (repo / "_site/paper-previews/lit-review/latex/html/index.html").exists()


def test_paper_directory_with_spaces_and_quotes_builds(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    name = 'my paper &"'
    run("git", "mv", "paper", name, cwd=repo)
    run("git", "commit", "-qm", "rename paper", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / name / "main.tex").write_text("newer")
    run("git", "commit", "-qam", "edit paper", cwd=repo)

    run("bash", str(SCRIPT), base, name, cwd=repo, env=env)

    assert (repo / "_site/paper-previews" / name / "main.pdf").exists()
    assert (repo / "_site/paper-previews" / name / "html-diff/index.html").exists()
    assert not list((repo / name).glob("what-changed.*.tex"))


def test_latexml_failure_keeps_pdf_and_log(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    (bin_dir / "latexmlc").write_text(
        '#!/bin/bash\nfor arg in "$@"; do case "$arg" in --dest=*) dest=${arg#--dest=};; --log=*) log=${arg#--log=};; esac; done\nprintf partial > "$dest"\nprintf "Error: unsupported package\\n" > "$log"\nexit 1\n'
    )

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert (repo / "_site/paper-previews/paper/what-changed.pdf").exists()
    assert not (repo / "_site/paper-previews/paper/html/index.html").exists()
    assert not (repo / "_site/paper-previews/paper/html-diff/index.html").exists()
    assert (repo / "_site/paper-previews/paper/html/latexml.log").exists()


def test_missing_latexmlc_writes_a_published_failure_log(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    (bin_dir / "latexmlc").unlink()

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert (
        "latexmlc is not installed"
        in (repo / "_site/paper-previews/paper/html/latexml.log").read_text()
    )


def test_single_latexml_error_is_not_published_as_html(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    (bin_dir / "latexmlc").write_text(
        '#!/bin/bash\nfor arg in "$@"; do case "$arg" in --dest=*) dest=${arg#--dest=};; --log=*) log=${arg#--log=};; esac; done\nprintf html > "$dest"\nprintf "Conversion complete: 1 error; 0 warnings\\n" > "$log"\n'
    )

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert not (repo / "_site/paper-previews/paper/html/index.html").exists()
    assert not (repo / "_site/paper-previews/paper/html-diff/index.html").exists()
    assert (
        json.loads((repo / "_site/paper-previews/paper/preview.json").read_text())[
            "html_diff"
        ]
        is False
    )


def test_html_diff_survives_diff_pdf_failure(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    with (bin_dir / "latexmk").open("a") as mock:
        mock.write('if [[ "$name" == what-changed.* ]]; then exit 1; fi\n')

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert not (repo / "_site/paper-previews/paper/what-changed.pdf").exists()
    assert (repo / "_site/paper-previews/paper/html-diff/index.html").exists()
    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {
        "changed": True,
        "diff": False,
        "html_diff": True,
        "other_inputs": False,
    }


def test_new_paper_links_current_pdf_without_diff_warning(tmp_path):
    repo, base, env, _ = paper_repo(tmp_path, old_paper=False)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {
        "changed": True,
        "diff": False,
        "new": True,
    }


def test_paper_preview_rejects_unresolved_citations(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    env["FAKE_BIBTEX_LOG"] = 'Warning--I didn\'t find a database entry for "missing"'

    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=repo, env=env, capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "Unresolved paper citations" in result.stdout
    assert not (repo / "_site/paper-previews/paper/main.pdf").exists()


def test_paper_preview_rejects_missing_bibliography_command(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    env["FAKE_BIBTEX_LOG"] = (
        r"I found no \bibdata command---while reading file main.aux"
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=repo, env=env, capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "Unresolved paper citations" in result.stdout
    assert not (repo / "_site/paper-previews/paper/main.pdf").exists()


def test_paper_preview_rejects_undefined_citation_in_latex_log(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    env["FAKE_LATEX_LOG"] = "LaTeX Warning: Citation `missing' on page 1 undefined"

    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=repo, env=env, capture_output=True, text=True
    )

    assert result.returncode != 0
    assert not (repo / "_site/paper-previews/paper/main.pdf").exists()


def test_paper_preview_publishes_arxiv_bibliography(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    env["FAKE_BBL"] = r"\begin{thebibliography}{1}"

    run("bash", str(SCRIPT), cwd=repo, env=env)

    assert (repo / "_site/paper-previews/paper/main.bbl").read_text().strip() == env[
        "FAKE_BBL"
    ]


def test_unchanged_paper_has_no_diff_manifest(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {"changed": False}


def test_missing_comparison_base_still_builds_current_pdf(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)

    run("bash", str(SCRIPT), "", cwd=repo, env=env)

    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {"changed": False}


def test_missing_recorder_keeps_current_pdf_without_failing_build(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    with (bin_dir / "latexmk").open("a") as mock:
        mock.write("rm -f build/main.fls\n")

    result = run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert "Could not compare paper versions" in result.stdout
    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {
        "changed": True,
        "diff": False,
    }


def test_missing_git_base_keeps_current_pdf_without_failing_build(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)

    result = run("bash", str(SCRIPT), "missing-base", cwd=repo, env=env)

    assert "Could not compare paper versions" in result.stdout
    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert (
        json.loads((repo / "_site/paper-previews/paper/preview.json").read_text())[
            "diff"
        ]
        is False
    )


def test_latexdiff_failure_keeps_current_pdf(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    (bin_dir / "latexdiff").write_text("#!/bin/bash\nexit 1\n")

    result = run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert "Could not build latexdiff PDF" in result.stdout
    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {
        "changed": True,
        "diff": False,
        "other_inputs": False,
    }


def test_thumbnail_failure_keeps_diff_pdf(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    (bin_dir / "pdftoppm").write_text("#!/bin/bash\nexit 1\n")

    result = run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert "Could not render paper diff thumbnails" in result.stdout
    assert (repo / "_site/paper-previews/paper/what-changed.pdf").exists()
    assert not list((repo / "_site/paper-previews/paper").glob("diff-page-*.png"))
    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {
        "changed": True,
        "diff": True,
        "html_diff": True,
        "other_inputs": False,
        "thumbnail_limit": 12,
    }


def test_diff_records_actual_page_count_for_thumbnail_note(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    (bin_dir / "pdfinfo").write_text("#!/bin/sh\necho 'Pages: 13'\n")
    (bin_dir / "pdfinfo").chmod(0o755)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (
        json.loads((repo / "_site/paper-previews/paper/preview.json").read_text())[
            "page_count"
        ]
        == 13
    )


def test_diff_does_not_delete_a_tracked_paper_file(tmp_path):
    repo, base, env, _ = paper_repo(tmp_path)
    tracked = repo / "paper/what-changed.tex"
    tracked.write_text("keep this file")
    run("git", "add", "paper/what-changed.tex", cwd=repo)
    run("git", "commit", "-qm", "add tracked file", cwd=repo)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert tracked.read_text() == "keep this file"
    assert not list((repo / "paper").glob("what-changed.*.tex"))


def test_unread_paper_file_does_not_claim_paper_changed(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "paper/README.md").write_text("new notes")
    run("git", "add", "paper/README.md", cwd=repo)
    run("git", "commit", "-qm", "add paper notes", cwd=repo)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {"changed": False}


def test_changed_included_subdirectory_tex_builds_diff(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    subdir = repo / "paper/sections"
    subdir.mkdir()
    section = subdir / "intro.tex"
    section.write_text("old")
    run("git", "add", "paper/sections/intro.tex", cwd=repo)
    run("git", "commit", "-qm", "add section", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    section.write_text("new")
    run("git", "commit", "-qam", "edit section", cwd=repo)
    env["FAKE_LATEX_INPUT"] = "sections/intro.tex"

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper-previews/paper/what-changed.pdf").exists()
    assert (
        json.loads((repo / "_site/paper-previews/paper/preview.json").read_text())[
            "diff"
        ]
        is True
    )


def test_root_level_tex_input_is_detected_without_false_diff_highlights(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    (repo / "shared.tex").write_text("old")
    run("git", "add", "shared.tex", cwd=repo)
    run("git", "commit", "-qm", "add shared input", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "shared.tex").write_text("new")
    run("git", "commit", "-qam", "edit shared input", cwd=repo)
    env["FAKE_LATEX_INPUT"] = "../shared.tex"

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert not (repo / "_site/paper-previews/paper/what-changed.pdf").exists()
    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {
        "changed": True,
        "diff": False,
        "other_inputs": True,
    }


def test_bibliography_only_edit_links_unmarked_current_pdf(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    (repo / "references.bib").write_text("old")
    run("git", "add", "references.bib", cwd=repo)
    run("git", "commit", "-qm", "add bibliography", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "references.bib").write_text("new")
    run("git", "commit", "-qam", "edit bibliography", cwd=repo)
    env["FAKE_LATEX_DEPS"] = "../references.bib"

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper-previews/paper/main.pdf").exists()
    assert not (repo / "_site/paper-previews/paper/what-changed.pdf").exists()
    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {
        "changed": True,
        "diff": False,
        "other_inputs": True,
    }


def test_unused_bibliography_edit_does_not_mark_paper_changed(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    (repo / "unused.bib").write_text("old")
    run("git", "add", "unused.bib", cwd=repo)
    run("git", "commit", "-qm", "add unused bibliography", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "unused.bib").write_text("new")
    run("git", "commit", "-qam", "edit unused bibliography", cwd=repo)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {"changed": False}


def test_dependency_comment_does_not_mark_unused_bibliography_changed(tmp_path):
    repo, _, env, bin_dir = paper_repo(tmp_path)
    (repo / "unused.bib").write_text("old")
    run("git", "add", "unused.bib", cwd=repo)
    run("git", "commit", "-qm", "add unused bibliography", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "unused.bib").write_text("new")
    run("git", "commit", "-qam", "edit unused bibliography", cwd=repo)
    with (bin_dir / "latexmk").open("a") as mock:
        mock.write('sed -i "1i# Header: ../unused.bib" build/main.dep\n')

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {"changed": False}


def test_latexmkrc_change_is_a_paper_input(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    (repo / "paper/.latexmkrc").write_text("old")
    run("git", "add", "paper/.latexmkrc", cwd=repo)
    run("git", "commit", "-qm", "add configuration", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "paper/.latexmkrc").write_text("new")
    run("git", "commit", "-qam", "edit configuration", cwd=repo)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {
        "changed": True,
        "diff": False,
        "other_inputs": True,
    }


def test_preamble_only_edit_links_pdf_without_highlights(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    (bin_dir / "latexdiff").write_text(
        "#!/bin/bash\nprintf '\\\\usepackage{new}\\n\\\\begin{document}\\nbody\\n'\n"
    )

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert not (repo / "_site/paper-previews/paper/what-changed.pdf").exists()
    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {
        "changed": True,
        "diff": False,
        "other_inputs": False,
        "unhighlighted": True,
    }


@pytest.mark.parametrize("escape", ["none", "unix", "nmake"])
@pytest.mark.parametrize(
    "name",
    [
        "shared refs.bib",
        " leading.bib",
        "trailing.bib ",
        r"literal\ refs.bib",
        "literal^ refs.bib",
    ],
)
def test_bibliography_path_with_spaces_is_detected(tmp_path, name, escape):
    repo, _, env, _ = paper_repo(tmp_path)
    bibliography = repo / name
    bibliography.write_text("old")
    run("git", "add", bibliography.name, cwd=repo)
    run("git", "commit", "-qm", "add bibliography", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    bibliography.write_text("new")
    run("git", "commit", "-qam", "edit bibliography", cwd=repo)
    env["FAKE_LATEX_DEPS"] = f"../{name}"
    env["FAKE_DEPS_ESCAPE"] = escape

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    manifest = json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    )
    assert manifest["changed"] is True
    assert manifest["other_inputs"] is True


def test_multiple_dependencies_are_each_detected(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    for name in ("first.bib", "shared refs.bib"):
        (repo / name).write_text("old")
    run("git", "add", "first.bib", "shared refs.bib", cwd=repo)
    run("git", "commit", "-qm", "add bibliographies", cwd=repo)
    env["FAKE_LATEX_DEPS"] = "../first.bib\n../shared refs.bib"

    for name in ("first.bib", "shared refs.bib"):
        base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
        (repo / name).write_text("new")
        run("git", "commit", "-qam", "edit bibliography", cwd=repo)

        run("bash", str(SCRIPT), base, cwd=repo, env=env)

        assert json.loads(
            (repo / "_site/paper-previews/paper/preview.json").read_text()
        ) == {"changed": True, "diff": False, "other_inputs": True}


def test_multiple_dependency_targets_and_phony_rules_are_supported(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    with (bin_dir / "latexmk").open("a") as mock:
        mock.write(
            "printf 'build/main.dvi :\\\\\\n    main.tex\\nmain.tex :\\n' >> build/main.dep\n"
        )

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    manifest = json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    )
    assert manifest["diff"] is True
    assert manifest["other_inputs"] is False


@pytest.mark.parametrize(
    "suffix", ["unexpected text\n", "bad-target:\n", "build/extra.pdf :\\\n"]
)
def test_invalid_trailing_dependency_output_uses_visible_fallback(tmp_path, suffix):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    with (bin_dir / "latexmk").open("a") as mock:
        mock.write('printf "%s" "$FAKE_DEP_SUFFIX" >> build/main.dep\n')
    env["FAKE_DEP_SUFFIX"] = suffix

    result = run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert "Could not compare paper versions" in result.stdout
    assert json.loads(
        (repo / "_site/paper-previews/paper/preview.json").read_text()
    ) == {"changed": True, "diff": False}
